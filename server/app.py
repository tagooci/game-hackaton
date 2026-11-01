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

from .app_helpers import (
    broadcast,
    credentials,
    is_number,
    read_json_object,
    send,
    send_error,
    send_v2_error,
    session_response,
    world_resources,
)
from .vehicle import Controls, VehicleConfig, VehicleState
from .auth import AuthService
from .db import Database
from .state import (
    add_player,
    others_view,
    players,
    public_view,
    remove_player,
    snapshot_view,
    mark_scene_ready,
    v2_connections,
    v2_players,
    v2_scene_ready,
)
from .scenarios import (
    ScenarioDefinition,
    ScenarioEvent,
    ScenarioManager,
    ScenarioRole,
    ScenarioZone,
)
from .scenario_handlers import ScenarioHandlers
from .simulation import run_physics, run_snapshots
from .world_physics import VehicleWorld

TICK_RATE = 20
PROTOCOL_VERSION = 1
tick = 0
VEHICLE_CONFIG = VehicleConfig()
PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def physics_loop():
    await run_physics(
        v2_players,
        v2_scene_ready,
        vehicle_world,
        VEHICLE_CONFIG,
        lambda player_id, x, z, speed: scenario_handlers.send_events(
            scenario_manager.observe(player_id, x, z, speed)
        ),
        lambda: tick,
    )

V2_PROTOCOL_VERSION = 2
STATIC_DIR = Path(__file__).resolve().parent.parent / 'client' / 'dist'
WORLD_MAP = json.loads((Path(__file__).resolve().parent.parent / 'client/public/content/world/manifest.json').read_text())
NAVIGATION = json.loads((Path(__file__).resolve().parent.parent / 'client/public/content/world/navigation.json').read_text())
vehicle_world = VehicleWorld(NAVIGATION['surfaces'],NAVIGATION.get('colliders',()),NAVIGATION.get('ceilings',()))
SESSION_COOKIE = "game_session"
database = Database()
auth = AuthService(database)
scenario_manager = ScenarioManager((
    ScenarioDefinition(
        id="priority-test",
        map_id=WORLD_MAP["worldId"],
        zone=ScenarioZone("junction-waiting", 56.0, 61.0, 36.0, 44.0),
        roles=(
            ScenarioRole(
                "main-straight",
                spawn=(58.5, 28.0, math.pi),
                destination=ScenarioZone("south-exit", 56.8, 60.2, 4.0, 10.0),
            ),
            ScenarioRole(
                "secondary-turn",
                spawn=(70.0, 20.0, -math.pi / 2),
                destination=ScenarioZone("north-exit", 62.0, 68.0, 28.0, 32.0),
            ),
        ),
    ),
))


async def snapshot_loop():
    global tick
    def next_tick() -> int:
        global tick
        tick += 1
        return tick

    await run_snapshots(
        players,
        v2_players,
        v2_connections,
        v2_scene_ready,
        VEHICLE_CONFIG,
        snapshot_view,
        send,
        TICK_RATE,
        next_tick,
    )


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
            if player["sceneKind"] != "world":
                continue
            state = player["vehicle"]
            database.save_safe_position(
                player["id"], state.x, state.z, state.heading,
                player["vertical"].y, WORLD_MAP["worldId"],
            )
        v2_players.clear()
        database.close()

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def content_no_store(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/content/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/health')
async def get_health():
    return {'status': 'ok'}


@app.post("/api/v2/login")
async def login(request: Request):
    body = await read_json_object(request)
    username, password = credentials(body)

    account = auth.authenticate(username, password)
    if account is None:
        raise HTTPException(status_code=401, detail="invalid credentials")

    return session_response(account, auth.create_session(account["playerId"]), SESSION_COOKIE)


@app.post("/api/v2/register")
async def register(request: Request):
    body = await read_json_object(request)
    username, password = credentials(body)
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
    return session_response(account, auth.create_session(player_id), SESSION_COOKIE)


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
    world_bytes = WORLD_MAP["worldBytes"] + sum(
        resource["bytes"] for resource in world_resources(PROJECT_ROOT)
    )
    return {
        "worldId": WORLD_MAP["worldId"],
        "contentVersion": WORLD_MAP["contentVersion"],
        "worldBytes": world_bytes,
        "cacheBudgetBytes": world_bytes // 10,
        "accounting": "unique_resource_bytes",
    }


def world_scene_prepare(player):
    state, body = player['vehicle'], player['vertical']
    return {
        "type": "scene_prepare", "sceneId": player['sceneId'], "epoch": player['epoch'],
        "sceneKind": player['sceneKind'], "mapId": WORLD_MAP['worldId'],
        "scenarioId": None, "roleId": None, "vehicleType": "car",
        "spawn": {"x": state.x, "z": state.z, "heading": state.heading, "y": body.y, "pitch": body.pitch},
        "participants": [],
        "plan": {"revision": 1, "chunkIds": [], "resources": world_resources(PROJECT_ROOT),
                 "mapManifestUrl": "/content/world/manifest.json"},
        "timeoutMs": 30000,
    }


def scenario_scene_prepare(player, session) -> dict:
    state, body = player["vehicle"], player["vertical"]
    return {
        "type": "scene_prepare",
        "sceneId": player["sceneId"],
        "epoch": player["epoch"],
        "sceneKind": "scenario",
        "mapId": session.definition.map_id,
        "scenarioId": session.definition.id,
        "roleId": player["roleId"],
        "vehicleType": "car",
        "spawn": {
            "x": state.x,
            "z": state.z,
            "heading": state.heading,
            "y": body.y,
            "pitch": body.pitch,
        },
        "participants": [
            {
                "id": participant_id,
                "name": v2_players[participant_id]["name"],
                "roleId": role_id,
                "vehicleType": "car",
            }
            for participant_id, role_id in session.participants.items()
        ],
        "plan": {
            "revision": 1,
            "chunkIds": [],
            "resources": world_resources(PROJECT_ROOT),
            "mapManifestUrl": "/content/world/manifest.json",
        },
        "timeoutMs": 30000,
    }


scenario_handlers = ScenarioHandlers(
    manager=scenario_manager,
    players=v2_players,
    connections=v2_connections,
    scene_ready=v2_scene_ready,
    vehicle_world=vehicle_world,
    world_map=WORLD_MAP,
    send=send,
    save_result=database.save_scenario_result,
    world_scene_prepare=world_scene_prepare,
    scenario_scene_prepare=scenario_scene_prepare,
)


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
                if (player_id not in v2_scene_ready or message.get('sceneId') != player["sceneId"]
                        or type(message.get('epoch')) is not int or message['epoch'] != player["epoch"]):
                    continue
                await scenario_handlers.send_events(scenario_manager.leave(player_id))
                player.pop("roleId", None)
                player.pop("scenarioSessionId", None)
                v2_scene_ready.discard(player_id)
                player_epoch = player["epoch"] + 1
                state = VehicleState(**WORLD_MAP['spawn'])
                body = vehicle_world.restore(state.x, state.z, state.heading, WORLD_MAP.get('spawnY', 0))
                player.update(vehicle=state, vertical=body, controls=Controls(brake=1),
                              seq=0, applied_seq=0, input_time=0.0, epoch=player_epoch)
                database.save_safe_position(player_id, state.x, state.z, state.heading, body.y, WORLD_MAP['worldId'])
                await send(websocket, world_scene_prepare(player))
                continue

            if msg_type == "scenario_join":
                if (
                    player["sceneKind"] != "world"
                    or player["sceneId"] != "world:main"
                    or player_id not in v2_scene_ready
                ):
                    await send_v2_error(websocket, "scenario_forbidden", "scenario is only available in the world")
                    continue
                scenario_id = message.get("scenarioId")
                if not isinstance(scenario_id, str):
                    await send_v2_error(websocket, "bad_value", "scenarioId must be a string")
                    continue
                events = scenario_manager.join(
                    player_id,
                    scenario_id,
                    player["vehicle"].x,
                    player["vehicle"].z,
                    player["vehicle"].speed,
                    now,
                )
                for event in events:
                    if event.type == "scenario_assigned" and event.player_id is not None:
                        assigned_player = v2_players.get(event.player_id)
                        if assigned_player is not None:
                            assigned_player["roleId"] = event.role_id
                            assigned_player["scenarioSessionId"] = event.session_id
                session_ids = {
                    event.session_id for event in events
                    if event.type == "scenario_assigned" and event.session_id is not None
                }
                for session_id in session_ids:
                    await scenario_handlers.prepare_session(session_id)
                await scenario_handlers.send_events(events)
                continue

            if msg_type == "scenario_leave":
                await scenario_handlers.send_events(scenario_manager.leave(player_id))
                player.pop("roleId", None)
                player.pop("scenarioSessionId", None)
                continue

            if msg_type == "scene_ready":
                if (
                    message.get("sceneId") == player["sceneId"]
                    and type(message.get("epoch")) is int and message.get("epoch") == player["epoch"]
                    and type(message.get("revision")) is int and message.get("revision") == 1
                    and player_id not in v2_scene_ready
                ):
                    start_events = scenario_manager.mark_ready(
                        player["scenarioSessionId"],
                        player_id,
                        tick + 2,
                    ) if player["sceneKind"] == "scenario" else []
                    if player["sceneKind"] == "world":
                        mark_scene_ready(player_id, tick + 1)
                        start_events = [ScenarioEvent(
                            "scene_start", "", None, player_id, start_tick=tick + 1,
                        )]
                    else:
                        player["start_tick"] = tick + 2
                        v2_scene_ready.add(player_id)
                    if start_events:
                        for event in start_events:
                            participant = v2_players[event.player_id]
                            v2_scene_ready.add(event.player_id)
                            participant["start_tick"] = event.start_tick
                            await send(v2_connections[event.player_id], {
                                "type": "scene_start",
                                "sceneId": participant["sceneId"],
                                "epoch": participant["epoch"],
                                "startTick": event.start_tick,
                                "tick": tick,
                            })
                continue
            if msg_type == "input":
                if (player_id not in v2_scene_ready or tick < player.get("start_tick", 0)
                        or message.get("sceneId") != player["sceneId"]
                        or type(message.get("epoch")) is not int or message.get("epoch") != player["epoch"]):
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
            if player["sceneKind"] == "world":
                database.save_safe_position(
                    player_id, state.x, state.z, state.heading,
                    player["vertical"].y, WORLD_MAP["worldId"],
                )
            await scenario_handlers.send_events(scenario_manager.leave(player_id))
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
                    players,
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
            await broadcast(players, {"type": "player_left", "id": player["id"]})
            print(f"Left: {player['id']}")


if STATIC_DIR.is_dir():
    app.mount('/', StaticFiles(directory=STATIC_DIR, html=True), name='static')
else:
    @app.get('/')
    async def get_build_status():
        return {"status": "client_not_built", "hint": "Run npm ci && npm run build in client/, then restart the server"}
