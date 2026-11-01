"""WebSocket lifecycle handlers for the v2 multiplayer protocol."""

import asyncio
import json
import os
import secrets
from contextlib import suppress
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .app_helpers import is_number, send, send_v2_error
from .vehicle import Controls, VehicleState


class V2WebSocketHandler:
    def __init__(
        self,
        auth: Any,
        database: Any,
        scenario_manager: Any,
        scenario_handlers: Any,
        vehicle_world: Any,
        world_map: dict[str, Any],
        players: dict[str, dict[str, Any]],
        connections: dict[str, WebSocket],
        scene_ready: set[str],
        world_scene_prepare: Any,
        get_tick: Any,
        protocol_version: int = 2,
    ) -> None:
        self.auth = auth
        self.database = database
        self.scenario_manager = scenario_manager
        self.scenario_handlers = scenario_handlers
        self.vehicle_world = vehicle_world
        self.world_map = world_map
        self.players = players
        self.connections = connections
        self.scene_ready = scene_ready
        self.world_scene_prepare = world_scene_prepare
        self.get_tick = get_tick
        self.protocol_version = protocol_version

    async def handle(self, websocket: WebSocket, session_cookie: str) -> None:
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
        account = self.auth.account_for_session(
            websocket.cookies.get(session_cookie)
        )
        if account is None:
            await websocket.accept()
            await websocket.close(code=1008)
            return

        await websocket.accept()
        player_id = account["playerId"]
        previous = self.connections.get(player_id)
        if previous is not None:
            with suppress(Exception):
                await previous.close(code=4001)
        self.connections[player_id] = websocket
        self.scene_ready.discard(player_id)
        old = self.players.get(player_id)
        state = old["vehicle"] if old else VehicleState(
            *self.database.safe_position(player_id)
        )
        saved_world, elevation = self.database.safe_context(player_id)
        if not old and saved_world != self.world_map["worldId"]:
            state = VehicleState(**self.world_map["spawn"])
            elevation = self.world_map.get("spawnY", 0)
        vertical = (
            old["vertical"]
            if old
            else self.vehicle_world.restore(
                state.x, state.z, state.heading, elevation
            )
        )
        player = {
            "id": player_id,
            "name": account["name"],
            "ws": websocket,
            "v2": True,
            "vehicle": VehicleState(state.x, state.z, state.heading),
            "controls": Controls(brake=1),
            "sceneId": "world:main",
            "sceneKind": "world",
            "epoch": 1,
            "seq": 0,
            "input_time": 0.0,
            "vertical": vertical,
            "color": old["color"] if old else secrets.randbelow(5),
        }
        self.players[player_id] = player
        await self._receive_messages(websocket, account, player)

    async def _receive_messages(
        self,
        websocket: WebSocket,
        account: dict[str, Any],
        player: dict[str, Any],
    ) -> None:
        player_id = player["id"]
        window_start = asyncio.get_running_loop().time()
        message_count = 0
        rate_strikes = 0
        joined = False

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
                        await send_v2_error(
                            websocket,
                            "rate_limited",
                            "maximum 60 messages per second",
                        )
                        await websocket.close(code=1008)
                        return
                    continue
                msg_type = message.get("type")
                if not isinstance(msg_type, str):
                    await send_v2_error(websocket, "bad_message", "type must be a string")
                    continue
                if not joined:
                    join_result = await self._handle_join(
                        websocket, account, player, msg_type, message
                    )
                    if join_result is None:
                        return
                    joined = join_result
                    continue

                if msg_type == "respawn":
                    await self._handle_respawn(websocket, player, message)
                elif msg_type == "scenario_join":
                    await self._handle_scenario_join(player, message, now, websocket)
                elif msg_type == "scenario_leave":
                    await self._handle_scenario_leave(player)
                elif msg_type == "scene_ready":
                    await self._handle_scene_ready(player, message, websocket)
                elif msg_type == "input":
                    await self._handle_input(player, message, now, websocket)
                else:
                    await send_v2_error(
                        websocket, "unknown_type", f"unknown type: {msg_type}"
                    )
        except WebSocketDisconnect:
            pass
        finally:
            await self._cleanup(websocket, player)

    async def _handle_join(
        self,
        websocket: WebSocket,
        account: dict[str, Any],
        player: dict[str, Any],
        msg_type: str,
        message: dict[str, Any],
    ) -> bool | None:
        if msg_type != "join":
            await send_v2_error(websocket, "not_joined", "send join first")
            return False
        if type(message.get("v")) is not int or message["v"] != self.protocol_version:
            await send_v2_error(websocket, "bad_version", "unsupported protocol version")
            await websocket.close(code=1008)
            return None
        await send(websocket, {
            "type": "welcome",
            "v": self.protocol_version,
            "playerId": player["id"],
            "connectionId": f"c-{secrets.token_urlsafe(12)}",
            "name": account["name"],
            "tick": self.get_tick(),
            "simulationHz": 30,
            "snapshotHz": 20,
            "inputHz": 20,
            "inputTimeoutMs": 250,
            "contentUrl": "/api/v2/content/bootstrap",
        })
        await send(websocket, self.world_scene_prepare(player))
        return True

    async def _handle_respawn(
        self, websocket: WebSocket, player: dict[str, Any], message: dict[str, Any]
    ) -> None:
        if player["sceneKind"] != "world" or player["sceneId"] != "world:main":
            await send_v2_error(
                websocket, "respawn_forbidden", "respawn is only available in the world"
            )
            return
        if (
            player["id"] not in self.scene_ready
            or message.get("sceneId") != player["sceneId"]
            or type(message.get("epoch")) is not int
            or message["epoch"] != player["epoch"]
        ):
            return
        await self.scenario_handlers.send_events(
            self.scenario_manager.leave(player["id"])
        )
        player.pop("roleId", None)
        player.pop("scenarioSessionId", None)
        self.scene_ready.discard(player["id"])
        state = VehicleState(**self.world_map["spawn"])
        body = self.vehicle_world.restore(
            state.x, state.z, state.heading, self.world_map.get("spawnY", 0)
        )
        player.update(
            vehicle=state,
            vertical=body,
            controls=Controls(brake=1),
            seq=0,
            applied_seq=0,
            input_time=0.0,
            epoch=player["epoch"] + 1,
            previous_vehicle=(state.x, state.z, 0.0),
        )
        self.database.save_safe_position(
            player["id"], state.x, state.z, state.heading,
            body.y, self.world_map["worldId"],
        )
        await send(websocket, self.world_scene_prepare(player))

    async def _handle_scenario_join(
        self,
        player: dict[str, Any],
        message: dict[str, Any],
        now: float,
        websocket: WebSocket,
    ) -> None:
        if (
            player["sceneKind"] != "world"
            or player["sceneId"] != "world:main"
            or player["id"] not in self.scene_ready
        ):
            await send_v2_error(websocket, "scenario_forbidden", "scenario is only available in the world")
            return
        scenario_id = message.get("scenarioId")
        if not isinstance(scenario_id, str):
            await send_v2_error(websocket, "bad_value", "scenarioId must be a string")
            return
        events = self.scenario_manager.join(
            player["id"], scenario_id, player["vehicle"].x,
            player["vehicle"].z, player["vehicle"].speed, now,
        )
        for event in events:
            if event.type == "scenario_assigned" and event.player_id is not None:
                assigned_player = self.players.get(event.player_id)
                if assigned_player is not None:
                    assigned_player["roleId"] = event.role_id
                    assigned_player["scenarioSessionId"] = event.session_id
        session_ids = {
            event.session_id for event in events
            if event.type == "scenario_assigned" and event.session_id is not None
        }
        for session_id in session_ids:
            await self.scenario_handlers.prepare_session(session_id)
        await self.scenario_handlers.send_events(events)

    async def _handle_scenario_leave(self, player: dict[str, Any]) -> None:
        await self.scenario_handlers.leave_to_return_spawn(player["id"])

    async def _handle_scene_ready(
        self, player: dict[str, Any], message: dict[str, Any], websocket: WebSocket
    ) -> None:
        if not (
            message.get("sceneId") == player["sceneId"]
            and type(message.get("epoch")) is int
            and message["epoch"] == player["epoch"]
            and type(message.get("revision")) is int
            and message["revision"] == 1
            and player["id"] not in self.scene_ready
        ):
            return
        start_events = (
            self.scenario_manager.mark_ready(
                player.get("scenarioSessionId"), player["id"], self.get_tick() + 2
            )
            if player["sceneKind"] == "scenario"
            else []
        )
        if player["sceneKind"] == "world":
            self.scene_ready.add(player["id"])
            player["start_tick"] = self.get_tick() + 1
            start_events = [("scene_start", player["id"], player["start_tick"])]
        else:
            player["start_tick"] = self.get_tick() + 2
            self.scene_ready.add(player["id"])
        for event in start_events:
            if isinstance(event, tuple):
                event_player_id, start_tick = event[1], event[2]
            else:
                event_player_id, start_tick = event.player_id, event.start_tick
            participant = self.players[event_player_id]
            self.scene_ready.add(event_player_id)
            participant["start_tick"] = start_tick
            await send(self.connections[event_player_id], {
                "type": "scene_start",
                "sceneId": participant["sceneId"],
                "epoch": participant["epoch"],
                "startTick": start_tick,
                "tick": self.get_tick(),
            })

    async def _handle_input(
        self,
        player: dict[str, Any],
        message: dict[str, Any],
        now: float,
        websocket: WebSocket,
    ) -> None:
        if (
            player["id"] not in self.scene_ready
            or self.get_tick() < player.get("start_tick", 0)
            or message.get("sceneId") != player["sceneId"]
            or type(message.get("epoch")) is not int
            or message["epoch"] != player["epoch"]
        ):
            return
        seq = message.get("seq")
        if type(seq) is not int or seq <= player["seq"] or seq > 9007199254740991:
            return
        axes = [message.get(key) for key in ("throttle", "steering", "brake")]
        if (
            not all(is_number(value) for value in axes)
            or not all(-1 <= value <= 1 for value in axes[:2])
            or not 0 <= axes[2] <= 1
        ):
            await send_v2_error(websocket, "bad_value", "invalid vehicle controls")
            return
        player.update(controls=Controls(*axes), seq=seq, input_time=now)

    async def _cleanup(self, websocket: WebSocket, player: dict[str, Any]) -> None:
        player_id = player["id"]
        if self.connections.get(player_id) is websocket:
            self.connections.pop(player_id, None)
            self.scene_ready.discard(player_id)
        if self.players.get(player_id) is player:
            state = player["vehicle"]
            if player["sceneKind"] == "world":
                self.database.save_safe_position(
                    player_id, state.x, state.z, state.heading,
                    player["vertical"].y, self.world_map["worldId"],
                )
            elif player["sceneKind"] == "scenario":
                session_id = player.get("scenarioSessionId")
                spawn = self.world_map["spawn"]
                body = self.vehicle_world.restore(
                    spawn["x"],
                    spawn["z"],
                    spawn["heading"],
                    self.world_map.get("spawnY", 0),
                )
                self.database.save_safe_position(
                    player_id,
                    spawn["x"],
                    spawn["z"],
                    spawn["heading"],
                    body.y,
                    self.world_map["worldId"],
                )
                if session_id is not None:
                    await self.scenario_handlers.cancel_session(
                        session_id,
                        exclude_player_id=player_id,
                    )
            self.players.pop(player_id, None)
