import json
import math
import os
import secrets
import sqlite3
from pathlib import Path
import asyncio

from contextlib import asynccontextmanager, suppress

from fastapi import Cookie, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .vehicle import Controls, VehicleConfig, VehicleState, step_vehicle, steering_angle
from .auth import AuthService
from .db import Database
from .world_physics import VehicleWorld

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
        for player in v2_players.values():
            if "vehicle" not in player:
                continue
            if player["id"] not in v2_scene_ready or tick < player.get("start_tick", 0):
                continue
            controls = player["controls"] if now - player["input_time"] <= 0.25 else Controls(brake=1)
            state = step_vehicle(player["vehicle"], controls, VEHICLE_CONFIG, dt)
            if player.get('v2'):
                others = [vehicle_world.car_box(other['vehicle'],other['vertical']) for other in v2_players.values()
                          if other['id'] != player['id'] and other['id'] in v2_scene_ready]
                state,player['vertical'] = vehicle_world.step(player['vehicle'],state,player['vertical'],dt,others)
            player["vehicle"] = state
            player["applied_seq"] = player.get("seq", 0)
            player.update(x=round(state.x, 2), z=round(state.z, 2), heading=round(state.heading, 2))

V2_PROTOCOL_VERSION = 2
STATIC_DIR = Path(__file__).resolve().parent.parent / 'client' / 'dist'
WORLD_MAP = json.loads((Path(__file__).resolve().parent.parent / 'client/public/content/world/manifest.json').read_text())
NAVIGATION = json.loads((Path(__file__).resolve().parent.parent / 'client/public/content/world/navigation.json').read_text())
vehicle_world = VehicleWorld(NAVIGATION['surfaces'],NAVIGATION.get('colliders',()),NAVIGATION.get('ceilings',()))
SESSION_COOKIE = "game_session"
database = Database()
auth = AuthService(database)
async def snapshot_loop():
    global tick
    while True:
        await asyncio.sleep(1 / TICK_RATE)
        tick += 1
        for player_id, ws in list(v2_connections.items()):
            if player_id not in v2_scene_ready:
                continue
            await send(ws, {
                "type": "snapshot",
                "sceneId": v2_players[player_id]["sceneId"],
                "epoch": v2_players[player_id]["epoch"],
                "tick": tick,
                "players": [_v2_player_snapshot(pid) for pid in v2_players if pid in v2_scene_ready],
                "signals": [],
            })


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.initialize()
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
        for player in v2_players.values():
            state = player["vehicle"]
            database.save_safe_position(player["id"], state.x, state.z, state.heading, player["vertical"].y, WORLD_MAP["worldId"])
        v2_players.clear()
        database.close()

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def content_no_store(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/content/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


async def send(ws: WebSocket, data: dict) -> bool:
    try:
        await ws.send_json(data)
        return True
    except Exception:
        return False

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


async def _read_json_object(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="expected JSON object") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="expected JSON object")
    return body


def _credentials(body: dict) -> tuple[str, str]:
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise HTTPException(
            status_code=400, detail="username and password are required"
        )
    return username, password


def _session_response(account: dict, token: str):
    from fastapi.responses import JSONResponse

    result = JSONResponse(
        {"playerId": account["playerId"], "name": account["name"]}
    )
    result.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=os.getenv("GAME_COOKIE_SECURE", "").lower() == "true",
        path="/",
    )
    return result


@app.post("/api/v2/login")
async def login(request: Request):
    body = await _read_json_object(request)
    username, password = _credentials(body)

    account = auth.authenticate(username, password)
    if account is None:
        raise HTTPException(status_code=401, detail="invalid credentials")

    return _session_response(account, auth.create_session(account["playerId"]))


@app.post("/api/v2/register")
async def register(request: Request):
    body = await _read_json_object(request)
    username, password = _credentials(body)
    name = body.get("name", username)
    if not isinstance(name, str):
        raise HTTPException(status_code=400, detail="name must be a string")
    try:
        player_id = auth.create_account(username, password, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="username already exists") from exc

    account = {"playerId": player_id, "name": name.strip()}
    return _session_response(account, auth.create_session(player_id))


@app.get("/api/v2/me")
async def get_me(game_session: str | None = Cookie(default=None)):
    account = auth.account_for_session(game_session)
    if account is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return account


@app.post("/api/v2/logout")
async def logout(game_session: str | None = Cookie(default=None)):
    player_id = auth.delete_session(game_session)
    if player_id is not None:
        connection = v2_connections.pop(player_id, None)
        v2_scene_ready.discard(player_id)
        if connection is not None:
            await connection.close(code=1000)
    from fastapi.responses import JSONResponse

    response = JSONResponse({"status": "ok"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/api/v2/content/bootstrap")
async def get_content_bootstrap(game_session: str | None = Cookie(default=None)):
    if auth.account_for_session(game_session) is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    world_bytes = WORLD_MAP["worldBytes"] + sum(resource["bytes"] for resource in world_resources())
    return {
        "worldId": WORLD_MAP["worldId"],
        "contentVersion": WORLD_MAP["contentVersion"],
        "worldBytes": world_bytes,
        "cacheBudgetBytes": world_bytes // 10,
        "accounting": "unique_resource_bytes",
    }


def world_resources() -> list[dict]:
    asset_dir = Path(__file__).resolve().parent.parent / "client" / "public" / "assets"
    return [
        {"id": relative, "url": f"/assets/{relative}", "bytes": (asset_dir / relative).stat().st_size}
        for relative in ("car-kit/sedan.glb", "car-kit/Textures/colormap.png")
    ]


def _v2_player_snapshot(player_id: str) -> dict:
    player = v2_players[player_id]
    state = player["vehicle"]
    return {
        "id": player_id, "name": player["name"], "vehicleType": "car", "roleId": None,
        **{key: round(getattr(state, key), 3) for key in ("x", "z", "heading", "speed", "steering")},
        "lastInputSeq": player.get("applied_seq", 0),
        "y": round(player["vertical"].y, 4), "pitch": round(player["vertical"].pitch, 4),
        "wheelAngle": round(steering_angle(state.speed, state.steering, VEHICLE_CONFIG), 4),
        "color": player["color"],
    }


async def send_v2_error(ws: WebSocket, code: str, text: str) -> None:
    await send(ws, {"type": "error", "code": code, "text": text})


def world_scene_prepare(player):
    state, body = player['vehicle'], player['vertical']
    return {
        "type": "scene_prepare", "sceneId": player['sceneId'], "epoch": player['epoch'],
        "sceneKind": player['sceneKind'], "mapId": WORLD_MAP['worldId'],
        "scenarioId": None, "roleId": None, "vehicleType": "car",
        "spawn": {"x": state.x, "z": state.z, "heading": state.heading, "y": body.y, "pitch": body.pitch},
        "participants": [],
        "plan": {"revision": 1, "chunkIds": [], "resources": world_resources(),
                 "mapManifestUrl": "/content/world/manifest.json"},
        "timeoutMs": 30000,
    }


@app.websocket("/ws/v2")
async def get_v2_websocket(websocket: WebSocket):
    allowed_origins = {
        origin.strip()
        for origin in os.getenv("GAME_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    }
    origin = websocket.headers.get("origin")
    if allowed_origins and origin not in allowed_origins:
        await websocket.accept()
        await websocket.close(code=1008)
        return
    account = auth.account_for_session(websocket.cookies.get(SESSION_COOKIE))
    if account is None:
        await websocket.accept()
        await websocket.close(code=1008)
        return

    await websocket.accept()
    player_id = account["playerId"]
    previous = v2_connections.get(player_id)
    if previous is not None:
        with suppress(Exception):
            await previous.close(code=4001)
    v2_connections[player_id] = websocket
    v2_scene_ready.discard(player_id)
    old = v2_players.get(player_id)
    state = old["vehicle"] if old else VehicleState(*database.safe_position(player_id))
    saved_world, elevation = database.safe_context(player_id)
    if not old and saved_world != WORLD_MAP['worldId']:
        state = VehicleState(**WORLD_MAP["spawn"])
        elevation = WORLD_MAP.get("spawnY",0)
    vertical = old['vertical'] if old else vehicle_world.restore(state.x,state.z,state.heading,elevation)
    player = {"id": player_id, "name": account["name"], "ws": websocket, "v2": True,
              "vehicle": VehicleState(state.x, state.z, state.heading), "controls": Controls(brake=1),
              "sceneId": "world:main", "sceneKind": "world", "epoch": 1,
              "seq": 0, "input_time": 0.0, "vertical": vertical, "color": old["color"] if old else secrets.randbelow(5)}
    v2_players[player_id] = player
    window_start = asyncio.get_running_loop().time()
    message_count = 0
    rate_strikes = 0
    joined = False
    scene_id = "world:main"
    epoch = 1

    try:
        while True:
            try:
                message = await websocket.receive_json()
            except (ValueError, json.JSONDecodeError):
                await send_v2_error(websocket, "bad_message", "expected JSON object")
                continue
            if not isinstance(message, dict):
                await send_v2_error(websocket, "bad_message", "expected JSON object")
                continue

            now = asyncio.get_running_loop().time()
            if now - window_start >= 1:
                window_start, message_count = now, 0
            message_count += 1
            if message_count > 60:
                rate_strikes += 1
                if rate_strikes >= 3:
                    await send_v2_error(websocket, "rate_limited", "maximum 60 messages per second")
                    await websocket.close(code=1008)
                    return
                continue
            msg_type = message.get("type")
            if not isinstance(msg_type, str):
                await send_v2_error(websocket, "bad_message", "type must be a string")
                continue
            if not joined:
                if msg_type != "join":
                    await send_v2_error(websocket, "not_joined", "send join first")
                    continue
                if type(message.get("v")) is not int or message["v"] != V2_PROTOCOL_VERSION:
                    await send_v2_error(websocket, "bad_version", "unsupported protocol version")
                    await websocket.close(code=1008)
                    return
                joined = True
                await send(
                    websocket,
                    {
                        "type": "welcome",
                        "v": V2_PROTOCOL_VERSION,
                        "playerId": player_id,
                        "connectionId": f"c-{secrets.token_urlsafe(12)}",
                        "name": account["name"],
                        "tick": tick,
                        "simulationHz": 30,
                        "snapshotHz": 20,
                        "inputHz": 20,
                        "inputTimeoutMs": 250,
                        "contentUrl": "/api/v2/content/bootstrap",
                    },
                )
                await send(websocket, world_scene_prepare(player))
                continue

            if msg_type == "respawn":
                if player['sceneKind'] != 'world' or player['sceneId'] != 'world:main':
                    await send_v2_error(websocket, "respawn_forbidden", "respawn is only available in the world")
                    continue
                if (player_id not in v2_scene_ready or message.get('sceneId') != scene_id
                        or type(message.get('epoch')) is not int or message['epoch'] != epoch):
                    continue
                v2_scene_ready.discard(player_id)
                epoch += 1
                state = VehicleState(**WORLD_MAP['spawn'])
                body = vehicle_world.restore(state.x, state.z, state.heading, WORLD_MAP.get('spawnY', 0))
                player.update(vehicle=state, vertical=body, controls=Controls(brake=1),
                              seq=0, applied_seq=0, input_time=0.0, epoch=epoch)
                database.save_safe_position(player_id, state.x, state.z, state.heading, body.y, WORLD_MAP['worldId'])
                await send(websocket, world_scene_prepare(player))
                continue

            if msg_type == "scene_ready":
                if (
                    message.get("sceneId") == scene_id
                    and type(message.get("epoch")) is int and message.get("epoch") == epoch
                    and type(message.get("revision")) is int and message.get("revision") == 1
                    and player_id not in v2_scene_ready
                ):
                    mark_scene_ready(player_id, tick + 1)
                    await send(
                        websocket,
                        {
                            "type": "scene_start",
                            "sceneId": scene_id,
                            "epoch": epoch,
                            "startTick": tick + 1,
                            "tick": tick,
                        },
                    )
                continue
            if msg_type == "input":
                if (player_id not in v2_scene_ready or tick < player.get("start_tick", 0)
                        or message.get("sceneId") != scene_id or type(message.get("epoch")) is not int or message.get("epoch") != epoch):
                    continue
                seq = message.get("seq")
                if type(seq) is not int or seq <= player["seq"] or seq > 9007199254740991:
                    continue
                axes = [message.get(key) for key in ("throttle", "steering", "brake")]
                if not all(is_number(value) for value in axes) or not all(-1 <= value <= 1 for value in axes[:2]) or not 0 <= axes[2] <= 1:
                    await send_v2_error(websocket, "bad_value", "invalid vehicle controls")
                    continue
                player.update(controls=Controls(*axes), seq=seq, input_time=now)
                continue
            await send_v2_error(websocket, "unknown_type", f"unknown type: {msg_type}")
    except WebSocketDisconnect:
        pass
    finally:
        if v2_connections.get(player_id) is websocket:
            v2_connections.pop(player_id, None)
            v2_scene_ready.discard(player_id)
        if v2_players.get(player_id) is player:
            state = player["vehicle"]
            database.save_safe_position(player_id, state.x, state.z, state.heading, player["vertical"].y, WORLD_MAP["worldId"])
            v2_players.pop(player_id, None)


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
