import json
import math
import os
import secrets
import sqlite3
from dataclasses import replace
from pathlib import Path
import asyncio

from contextlib import asynccontextmanager, suppress

from fastapi import Cookie, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .state import players, add_player, remove_player, public_view, others_view, snapshot_view
from .vehicle import Controls, VehicleState, step_vehicle, steering_angle
from .vehicles import vehicle_definition, vehicle_profile
from .server_settings import ServerSettingsStore
from .auth import AuthService
from .db import Database
from .agent import FeedbackConfig, OllamaFeedbackGenerator, parse_result
import logging
from .scenarios import ScenarioSessions, SCENARIO, WORLD as scenario_world
from .world_physics import VehicleWorld

TICK_RATE = 20
tick = 0

PARTICIPATION_XP = 50
SHORT_SCENARIO_XP = 100
LONG_SCENARIO_XP = 200
VIOLATION_PENALTY_XP = 10
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
        for player in [*players.values(), *v2_players.values()]:
            if "vehicle" not in player:
                continue
            if player.get("v2") and (player["id"] not in v2_scene_ready or tick < player.get("start_tick", 0)):
                continue
            controls = player["controls"] if now - player["input_time"] <= 0.25 else Controls(brake=1)
            vehicle_config = vehicle_definition(player.get("vehicleType", "car")).physics
            state = step_vehicle(player["vehicle"], controls, vehicle_config, dt)
            if player.get('v2'):
                others = [{**vehicle_world.car_box(other['vehicle'],other['vertical']), 'playerId': other['id']} for other in v2_players.values()
                          if other['id'] != player['id'] and other['id'] in v2_scene_ready
                          and other['sceneId'] == player['sceneId']]
                world = scenario_world if player['sceneKind'] == 'scenario' else vehicle_world
                state,player['vertical'] = world.step(player['vehicle'],state,player['vertical'],dt,others)
                player['contact_players'] = world.contact_players
            player["vehicle"] = state
            player["applied_seq"] = player.get("seq", 0)
            player.update(x=round(state.x, 2), z=round(state.z, 2), heading=round(state.heading, 2))
        await scenarios.update(v2_players, v2_scene_ready, now, move_scene, send_prepare)

PROTOCOL_VERSION = 1
V2_PROTOCOL_VERSION = 2
STATIC_DIR = Path(__file__).resolve().parent.parent / 'client' / 'dist'
WORLD_MAP = json.loads((Path(__file__).resolve().parent.parent / 'client/public/content/world/manifest.json').read_text())
NAVIGATION = json.loads((Path(__file__).resolve().parent.parent / 'client/public/content/world/navigation.json').read_text())
vehicle_world = VehicleWorld(NAVIGATION['surfaces'],NAVIGATION.get('colliders',()),NAVIGATION.get('ceilings',()))
SESSION_COOKIE = "game_session"
database = Database()
auth = AuthService(database)
server_settings = ServerSettingsStore()
v2_connections: dict[str, WebSocket] = {}
v2_scene_ready: set[str] = set()
v2_players: dict[str, dict] = {}
agent_tasks = set()
agent_lock = asyncio.Lock()


async def generate_agent_feedback(report, connection, experience: int):
    try:
        result = parse_result(report)
        async with agent_lock:
            settings = server_settings.get()
            config = replace(
                FeedbackConfig.from_environment(),
                tone={
                    "coach": "coach",
                    "aggressive": "aggressive",
                }.get(settings["agentStyle"], "friendly"),
            )
            feedback = await OllamaFeedbackGenerator(config=config).generate(result)
        if v2_connections.get(result.player_id) is connection:
            feedback_payload = feedback.to_dict()
            feedback_payload["experience"] = f"{experience:+d} XP"
            await send(connection, {"type": "agent_feedback", "resultId": result.result_id,
                                   "sessionId": result.session_id, "playerId": result.player_id,
                                   "feedback": feedback_payload})
    except Exception:
        logging.getLogger(__name__).exception("Agent feedback failed for result %s", report['resultId'])
        if v2_connections.get(report['playerId']) is connection:
            await send(connection, {"type": "agent_feedback_error", "resultId": report['resultId'],
                                   "sessionId": report['sessionId'], "text": "Не удалось получить ответ локального ИИ"})


def submit_agent_result(report):
    result = parse_result(report)
    violations = len(result.violations)
    completion_xp = {
        "short": SHORT_SCENARIO_XP,
        "long": LONG_SCENARIO_XP,
    }[result.scenario_type.value] if result.status.value == "completed" else 0
    experience = max(
        0,
        PARTICIPATION_XP + completion_xp - violations * VIOLATION_PENALTY_XP,
    )
    database.save_scenario_result(
        result.result_id, result.session_id, result.scenario_id, result.player_id,
        result.role_id, result.status.value == "completed", experience,
        [violation.id for violation in result.violations],
    )
    connection = v2_connections.get(report['playerId'])
    if connection is None:
        return
    task = asyncio.create_task(generate_agent_feedback(report, connection, experience))
    agent_tasks.add(task)
    task.add_done_callback(agent_tasks.discard)


scenarios = ScenarioSessions(submit_agent_result)

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
            await send(ws, {
                "type": "snapshot",
                "sceneId": v2_players[player_id]["sceneId"],
                "epoch": v2_players[player_id]["epoch"],
                "tick": tick,
                "players": [_v2_player_snapshot(pid) for pid in v2_players if pid in v2_scene_ready and v2_players[pid]["sceneId"] == v2_players[player_id]["sceneId"]],
                "signals": [],
                "scenarioResult": v2_players[player_id].get("scenario_result"),
                "scenarioQueue": {"count": scenarios.count, "x": 60, "y": 5, "z": 20}
                    if v2_players[player_id]["sceneKind"] == "world" else None,
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
        players.clear()
        v2_connections.clear()
        v2_scene_ready.clear()
        for player in v2_players.values():
            save_position(player)
        v2_players.clear()
        for agent_task in list(agent_tasks):
            agent_task.cancel()
        await asyncio.gather(*agent_tasks, return_exceptions=True)
        agent_tasks.clear()
        database.close()

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def content_no_store(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(('/content/', '/assets/')):
        response.headers['Cache-Control'] = 'no-store'
    return response


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


def _level(experience: int) -> int:
    return experience // 100 + 1


async def _authenticated_account(game_session: str | None) -> dict:
    account = auth.account_for_session(game_session)
    if account is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return account


@app.get("/api/v2/profile")
async def get_profile(game_session: str | None = Cookie(default=None)):
    account = await _authenticated_account(game_session)
    profile = database.profile(account["playerId"])
    if profile is None:
        raise HTTPException(status_code=404, detail="account not found")
    return {
        **profile,
        "vehicles": vehicle_profile(profile["level"]),
        "isAdmin": server_settings.is_admin(account["username"]),
    }


async def _admin_account(game_session: str | None) -> dict:
    account = await _authenticated_account(game_session)
    if not server_settings.is_admin(account["username"]):
        raise HTTPException(status_code=403, detail="administrator access required")
    return account


@app.get("/api/v2/admin/settings")
async def get_admin_settings(game_session: str | None = Cookie(default=None)):
    await _admin_account(game_session)
    return server_settings.get()


@app.post("/api/v2/admin/settings")
async def update_admin_settings(
    request: Request, game_session: str | None = Cookie(default=None)
):
    await _admin_account(game_session)
    body = await _read_json_object(request)
    agent_style = body.get("agentStyle")
    weather = body.get("weather")
    if not isinstance(agent_style, str) or not isinstance(weather, str):
        raise HTTPException(status_code=400, detail="agentStyle and weather are required")
    try:
        return server_settings.update(agent_style=agent_style, weather=weather)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v2/admin/weather")
async def update_admin_weather(
    request: Request, game_session: str | None = Cookie(default=None)
):
    await _admin_account(game_session)
    body = await _read_json_object(request)
    weather = body.get("weather")
    if not isinstance(weather, str):
        raise HTTPException(status_code=400, detail="weather is required")
    try:
        return server_settings.update_weather(weather)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v2/profile")
async def update_profile(request: Request, game_session: str | None = Cookie(default=None)):
    account = await _authenticated_account(game_session)
    body = await _read_json_object(request)
    color = body.get("vehicleColor")
    vehicle_type = body.get("vehicleType")
    if type(color) is not int or not 0 <= color < 5:
        raise HTTPException(status_code=400, detail="vehicleColor must be between 0 and 4")
    profile = database.profile(account["playerId"])
    if profile is None:
        raise HTTPException(status_code=404, detail="account not found")
    try:
        definition = vehicle_definition(vehicle_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if definition.unlock_level > profile["level"]:
        raise HTTPException(
            status_code=403,
            detail=f"{vehicle_type} unlocks at level {definition.unlock_level}",
        )
    database.update_profile(account["playerId"], color, vehicle_type)
    return {
        **profile,
        "vehicleColor": color,
        "vehicleType": vehicle_type,
        "vehicles": vehicle_profile(profile["level"]),
    }


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
    world_bytes = WORLD_MAP["worldBytes"]
    return {
        "worldId": WORLD_MAP["worldId"],
        "contentVersion": WORLD_MAP["contentVersion"],
        "worldBytes": world_bytes,
        "cacheBudgetBytes": world_bytes // 10,
        "accounting": "unique_resource_bytes",
    }


def world_resources(vehicle_type: str) -> list[dict]:
    resources = list(WORLD_MAP['residentResources'])
    definition = vehicle_definition(vehicle_type)
    if not any(resource["id"] == definition.asset_id for resource in resources):
        resources.append({
            "id": definition.asset_id,
            "url": definition.asset_url,
            "kind": "model",
            "bytes": definition.asset_bytes,
            "encoding": "gzip",
            "label": definition.id,
        })
    return resources



def _v2_player_snapshot(player_id: str) -> dict:
    player = v2_players[player_id]
    state = player["vehicle"]
    return {
        "id": player_id, "name": player["name"], "vehicleType": player["vehicleType"], "roleId": player.get("roleId"),
        **{key: round(getattr(state, key), 3) for key in ("x", "z", "heading", "speed", "steering")},
        "lastInputSeq": player.get("applied_seq", 0),
        "y": round(player["vertical"].y, 4), "pitch": round(player["vertical"].pitch, 4),
        "wheelAngle": round(
            steering_angle(
                state.speed,
                state.steering,
                vehicle_definition(player["vehicleType"]).physics,
            ),
            4,
        ),
        "color": player["color"],
        "throttle": player["controls"].throttle if asyncio.get_running_loop().time()-player["input_time"] <= .25 else 0,
        "grounded": player["vertical"].grounded,
    }


async def send_v2_error(ws: WebSocket, code: str, text: str) -> None:
    await send(ws, {"type": "error", "code": code, "text": text})


def world_scene_prepare(player):
    state, body = player['vehicle'], player['vertical']
    return {
        "type": "scene_prepare", "sceneId": player['sceneId'], "epoch": player['epoch'],
        "sceneKind": player['sceneKind'], "mapId": WORLD_MAP['worldId'] + (':left-turn' if player['sceneKind'] == 'scenario' else ''),
        "scenarioId": SCENARIO["id"] if player["sceneKind"] == "scenario" else None, "roleId": player.get("roleId"), "vehicleType": player["vehicleType"],
        "weather": server_settings.get()["weather"],
        "spawn": {"x": state.x, "z": state.z, "heading": state.heading, "y": body.y, "pitch": body.pitch},
        "participants": [{"playerId": p["id"], "roleId": p.get("roleId"), "vehicleType": p["vehicleType"]}
                         for p in v2_players.values() if p["sceneId"] == player["sceneId"]]
                        if player["sceneKind"] == "scenario" else [],
        "plan": {"revision": 1, "chunkIds": [], "resources": world_resources(player["vehicleType"]),
                 "mapManifestUrl": SCENARIO["manifestUrl"] if player["sceneKind"] == "scenario" else "/content/world/manifest.json"},
        "finish": ({**SCENARIO["finishes"][player["roleId"]],
                    "y": max(h for h, _ in scenario_world.floors(
                        SCENARIO["finishes"][player["roleId"]]["x"], SCENARIO["finishes"][player["roleId"]]["z"],
                        SCENARIO["finishes"][player["roleId"]]["heading"], []))}
                   if player["sceneKind"] == "scenario" else None),
        "timeoutMs": 30000,
    }


async def move_scene(player, scene_id, role):
    v2_scene_ready.discard(player['id'])
    if scene_id:
        player['return_state'] = (player['vehicle'], player['vertical'])
        state = VehicleState(**SCENARIO['spawns'][role])
        body = scenario_world.restore(state.x, state.z, state.heading, .1)
    else:
        state, body = player.pop('return_state')
    player.update(vehicle=VehicleState(state.x, state.z, state.heading), vertical=body,
                  sceneId=scene_id or 'world:main', sceneKind='scenario' if scene_id else 'world',
                  scenario_result=None, roleId=('left-turn' if role == 0 else 'straight') if scene_id else None,
                  epoch=player['epoch']+1, seq=0, applied_seq=0, input_time=0,
                  controls=Controls(brake=1))
    if not scene_id:
        await send(player['ws'], world_scene_prepare(player))


async def send_prepare(player):
    await send(player['ws'], world_scene_prepare(player))


def save_position(player):
    state, body = player.get('return_state', (player['vehicle'], player['vertical']))
    database.save_safe_position(player['id'], state.x, state.z, state.heading, body.y, WORLD_MAP['worldId'])


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
    if old and old.get("return_state"):
        old["vehicle"], old["vertical"] = old.pop("return_state")
    state = old["vehicle"] if old else VehicleState(*database.safe_position(player_id))
    saved_world, elevation = database.safe_context(player_id)
    if not old and saved_world != WORLD_MAP['worldId']:
        state = VehicleState(**WORLD_MAP["spawn"])
        elevation = WORLD_MAP.get("spawnY",0)
    vertical = old['vertical'] if old else vehicle_world.restore(state.x,state.z,state.heading,elevation)
    player = {"id": player_id, "name": account["name"], "ws": websocket, "v2": True,
              "vehicle": VehicleState(state.x, state.z, state.heading), "controls": Controls(brake=1),
              "sceneId": "world:main", "sceneKind": "world", "epoch": 1,
              "seq": 0, "input_time": 0.0, "vertical": vertical,
              "color": old["color"] if old else account["vehicleColor"],
              "vehicleType": old["vehicleType"] if old else account["vehicleType"]}
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

            scene_id, epoch = player["sceneId"], player["epoch"]
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
                    player["start_tick"] = float("inf")
                    v2_scene_ready.add(player_id)
                    participants = (scenarios.start(scene_id, v2_scene_ready)
                                    if player['sceneKind'] == 'scenario' else [player_id])
                    for pid in participants:
                        participant = v2_players[pid]
                        participant['start_tick'] = tick + 1
                        await send(participant['ws'], {
                            'type': 'scene_start', 'sceneId': participant['sceneId'],
                            'epoch': participant['epoch'], 'startTick': tick+1, 'tick': tick,
                        })
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
            save_position(player)
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
