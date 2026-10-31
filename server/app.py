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

from .auth import AuthService
from .db import Database
from .state import (
    add_player,
    others_view,
    players,
    public_view,
    remove_player,
    snapshot_view,
)

TICK_RATE = 20
tick = 0

PROTOCOL_VERSION = 1
V2_PROTOCOL_VERSION = 2
STATIC_DIR = Path(__file__).resolve().parent.parent / 'client' / 'dist'
SESSION_COOKIE = "game_session"
database = Database()
auth = AuthService(database)
v2_connections: dict[str, WebSocket] = {}
v2_scene_ready: set[str] = set()

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
        for player_id, ws in list(v2_connections.items()):
            if player_id not in v2_scene_ready:
                continue
            account = auth.account_for_session(ws.cookies.get(SESSION_COOKIE))
            if account is None:
                continue
            await send(ws, {
                "type": "snapshot",
                "sceneId": "world:main",
                "epoch": 1,
                "tick": tick,
                "players": [_v2_player_snapshot(player_id, account["name"])],
                "signals": [],
            })


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.initialize()
    task = asyncio.create_task(snapshot_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        players.clear()
        v2_connections.clear()
        v2_scene_ready.clear()
        database.close()

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
    world_bytes = 0
    return {
        "worldId": "training-city",
        "contentVersion": "build-01",
        "worldBytes": world_bytes,
        "cacheBudgetBytes": world_bytes // 10,
        "accounting": "unique_resource_bytes",
    }


def _v2_player_snapshot(player_id: str, name: str) -> dict:
    x, z, heading = database.safe_position(player_id)
    return {
        "id": player_id,
        "name": name,
        "vehicleType": "car",
        "roleId": None,
        "x": round(x, 3),
        "z": round(z, 3),
        "heading": round(heading, 3),
        "speed": 0,
        "steering": 0,
        "lastInputSeq": 0,
    }


async def send_v2_error(ws: WebSocket, code: str, text: str) -> None:
    await send(ws, {"type": "error", "code": code, "text": text})


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

            msg_type = message.get("type")
            if not isinstance(msg_type, str):
                await send_v2_error(websocket, "bad_message", "type must be a string")
                continue
            if not joined:
                if msg_type != "join":
                    await send_v2_error(websocket, "not_joined", "send join first")
                    continue
                if message.get("v") != V2_PROTOCOL_VERSION:
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
                await send(
                    websocket,
                    {
                        "type": "scene_prepare",
                        "sceneId": scene_id,
                        "epoch": epoch,
                        "sceneKind": "world",
                        "mapId": "world",
                        "scenarioId": None,
                        "roleId": None,
                        "vehicleType": "car",
                        "spawn": {"x": 0, "z": 0, "heading": 0},
                        "participants": [],
                        "plan": {"revision": 1, "chunkIds": [], "resources": []},
                        "timeoutMs": 30000,
                    },
                )
                continue

            if msg_type == "scene_ready":
                if (
                    message.get("sceneId") == scene_id
                    and message.get("epoch") == epoch
                    and message.get("revision") == 1
                    and player_id not in v2_scene_ready
                ):
                    v2_scene_ready.add(player_id)
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
                await send_v2_error(websocket, "not_implemented", "vehicle physics is not available yet")
                continue
            await send_v2_error(websocket, "unknown_type", f"unknown type: {msg_type}")
    except WebSocketDisconnect:
        pass
    finally:
        if v2_connections.get(player_id) is websocket:
            v2_connections.pop(player_id, None)
            v2_scene_ready.discard(player_id)


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
