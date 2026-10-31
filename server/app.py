import json
import math
from pathlib import Path
import asyncio

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .state import players, add_player, remove_player, public_view, others_view, snapshot_view

TICK_RATE = 20
tick = 0

PROTOCOL_VERSION = 1
STATIC_DIR = Path(__file__).resolve().parent.parent / 'static'

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
    yield
    task.cancel()

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
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


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
            except json.JSONDecodeError:
                msg = None
            if not isinstance(msg, dict):
                await send_error(websocket, "bad_message", "expected JSON object")
                continue

            msg_type = msg.get("type")

            # до join принимаем только join
            if player is None:
                if msg_type != "join":
                    await send_error(websocket, "not_joined", "send join first")
                    continue

                if msg.get("v") != PROTOCOL_VERSION:
                    await send_error(websocket, "bad_version", "unsupported protocol version")
                    await websocket.close()
                    return

                name = msg.get("name")
                if not isinstance(name, str) or not (1 <= len(name.strip()) <= 24):
                    await send_error(websocket, "bad_value", "name must be a string, 1-24 chars")
                    continue

                player = add_player(websocket, name.strip())
                print(f"Joined: {player['id']} ({player['name']})")

                await send(websocket, {
                    "type": "welcome",
                    "id": player["id"],
                    "zone": player["zone"],
                    "x": player["x"],
                    "z": player["z"],
                    "heading": player["heading"],
                    "players": others_view(player["id"]),
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
                x, z, heading = msg.get("x"), msg.get("z"), msg.get("heading")
                if not all(is_number(v) for v in (x, z, heading)):
                    await send_error(websocket, "bad_value", "x, z, heading must be numbers")
                    continue
                player["x"] = round(x, 2)
                player["z"] = round(z, 2)
                player["heading"] = round(heading, 2)
            else:
                await send_error(websocket, "unknown_type", f"unknown type: {msg_type}")

    except WebSocketDisconnect:
        print('player disconnected')

    finally:
        if player is not None:
            remove_player(player["id"])
            await broadcast({"type": "player_left", "id": player["id"]})
            print(f"Left: {player['id']}")


app.mount('/', StaticFiles(directory=STATIC_DIR, html=True), name='static')
