import json
import math
from pathlib import Path
import asyncio

from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .state import players, add_player, remove_player, public_view, others_view, snapshot_view
from .vehicle import Controls, VehicleConfig, VehicleState, step_vehicle

TICK_RATE = 20
tick = 0
VEHICLE_CONFIG = VehicleConfig()


async def physics_loop():
    dt = 1 / 30
    loop = asyncio.get_running_loop()
    deadline = loop.time()
    while True:
        deadline += dt
        await asyncio.sleep(max(0, deadline - loop.time()))
        now = loop.time()
        if now - deadline > 0.2:
            deadline = now
        for player in list(players.values()):
            if "vehicle" not in player:
                continue
            controls = player["controls"] if now - player["input_time"] <= 0.25 else Controls(brake=1)
            state = step_vehicle(player["vehicle"], controls, VEHICLE_CONFIG, dt)
            player["vehicle"] = state
            player.update(x=round(state.x, 2), z=round(state.z, 2), heading=round(state.heading, 2))

PROTOCOL_VERSION = 1
STATIC_DIR = Path(__file__).resolve().parent.parent / 'client' / 'dist'

async def snapshot_loop():
    global tick
    while True:
        await asyncio.sleep(1 / TICK_RATE)
        tick += 1
        for p in list(players.values()):
            await send(p["ws"], {
                "type": "snapshot",
                "tick": tick,
                "players": snapshot_view(p["zone"]),
            })


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(snapshot_loop())
    physics_task = asyncio.create_task(physics_loop())
    try:
        yield
    finally:
        task.cancel()
        physics_task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(asyncio.CancelledError):
            await physics_task
        players.clear()

app = FastAPI(lifespan=lifespan)

async def send(ws: WebSocket, data: dict) -> bool:
    try:
        await ws.send_json(data)
        return True
    except Exception:
        return False

async def send_error(ws: WebSocket, code: str, text: str) -> None:
    await send(ws, {"type": "error", "code": code, "text": text})


async def broadcast(data: dict, exclude_id: str | None = None) -> None:
    for p in list(players.values()):
        if p["id"] != exclude_id:
            await send(p["ws"], data)


def is_number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@app.get('/health')
async def get_health():
    return {'status': 'ok'}


@app.websocket('/ws')
async def get_websocket(websocket: WebSocket):
    await websocket.accept()
    print('Client connected')
    player = None

    try:
        while True:
            text = await websocket.receive_text()

            try:
                msg = json.loads(text)
            except ValueError:
                msg = None
            if not isinstance(msg, dict):
                await send_error(websocket, "bad_message", "expected JSON object")
                continue

            msg_type = msg.get("type")
            if not isinstance(msg_type, str):
                await send_error(websocket, "bad_message", "type must be a string")
                continue

            # до join принимаем только join
            if player is None:
                if msg_type != "join":
                    await send_error(websocket, "not_joined", "send join first")
                    continue

                if not is_number(msg.get("v")) or msg["v"] != PROTOCOL_VERSION:
                    await send_error(websocket, "bad_version", "unsupported protocol version")
                    await websocket.close()
                    return

                name = msg.get("name")
                if not isinstance(name, str) or not (1 <= len(name.strip()) <= 24):
                    await send_error(websocket, "bad_value", "name must be a string, 1-24 chars")
                    continue

                control_mode = msg.get("controlMode", "state")
                if control_mode not in ("state", "vehicle"):
                    await send_error(websocket, "bad_value", "unsupported controlMode")
                    continue
                player = add_player(websocket, name.strip())
                if control_mode == "vehicle":
                    player.update(
                        vehicle=VehicleState(x=player["x"], z=player["z"]),
                        controls=Controls(brake=1), input_time=0, input_seq=0,
                    )
                print(f"Joined: {player['id']} ({player['name']})")

                await send(websocket, {
                    "type": "welcome",
                    "id": player["id"],
                    "zone": player["zone"],
                    "x": player["x"],
                    "z": player["z"],
                    "heading": player["heading"],
                    "players": others_view(player["id"]),
                    **({"controlMode": "vehicle", "sceneId": "world:main", "epoch": 1} if control_mode == "vehicle" else {}),
                })
                await broadcast(
                    {"type": "player_joined", **public_view(player)},
                    exclude_id=player["id"],
                )
                continue

            # после join
            if msg_type == "join":
                await send_error(websocket, "already_joined", "already joined")
            elif msg_type == "state":
                if "vehicle" in player:
                    await send_error(websocket, "bad_value", "vehicle accepts input, not state")
                    continue
                if not all(key in msg for key in ("x", "z", "heading")):
                    await send_error(websocket, "bad_message", "state requires x, z, heading")
                    continue
                x, z, heading = msg.get("x"), msg.get("z"), msg.get("heading")
                if not all(is_number(v) for v in (x, z, heading)):
                    await send_error(websocket, "bad_value", "x, z, heading must be numbers")
                    continue
                player["x"] = round(x, 2)
                player["z"] = round(z, 2)
                player["heading"] = round(heading, 2)
            elif msg_type == "input":
                if "vehicle" not in player:
                    await send_error(websocket, "bad_value", "join with controlMode vehicle first")
                    continue
                if not all(key in msg for key in ("sceneId", "epoch", "seq", "throttle", "steering", "brake")):
                    await send_error(websocket, "bad_message", "missing input fields")
                    continue
                seq = msg["seq"]
                if type(seq) is not int or not 1 <= seq <= 9007199254740991 or not all(
                    is_number(msg[key]) and low <= msg[key] <= high
                    for key, low, high in (("throttle", -1, 1), ("steering", -1, 1), ("brake", 0, 1))
                ):
                    await send_error(websocket, "bad_value", "invalid vehicle controls")
                    continue
                if msg["sceneId"] != "world:main" or type(msg["epoch"]) is not int or msg["epoch"] != 1 or seq <= player["input_seq"]:
                    continue
                player.update(
                    controls=Controls(msg["throttle"], msg["steering"], msg["brake"]),
                    input_time=asyncio.get_running_loop().time(), input_seq=seq,
                )
            else:
                await send_error(websocket, "unknown_type", f"unknown type: {msg_type}")

    except WebSocketDisconnect:
        print('player disconnected')

    finally:
        if player is not None:
            remove_player(player["id"])
            await broadcast({"type": "player_left", "id": player["id"]})
            print(f"Left: {player['id']}")


if STATIC_DIR.is_dir():
    app.mount('/', StaticFiles(directory=STATIC_DIR, html=True), name='static')
else:
    @app.get('/')
    async def get_build_status():
        return {"status": "client_not_built", "hint": "Run npm ci && npm run build in client/, then restart the server"}
