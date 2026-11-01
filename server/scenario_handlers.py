"""WebSocket orchestration for multiplayer scenarios."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket

from .scenarios import ScenarioEvent, ScenarioManager, ScenarioState
from .vehicle import Controls, VehicleState


SendMessage = Callable[[WebSocket, dict[str, Any]], Awaitable[bool]]
SaveResult = Callable[[str, str, str, str, str, bool, int, list[str]], bool]
SavePosition = Callable[[str, float, float, float, float, str], None]


class ScenarioHandlers:
    def __init__(
        self,
        manager: ScenarioManager,
        players: dict[str, dict[str, Any]],
        connections: dict[str, WebSocket],
        scene_ready: set[str],
        vehicle_world: Any,
        world_map: dict[str, Any],
        send: SendMessage,
        save_result: SaveResult,
        save_position: SavePosition,
        world_scene_prepare: Callable[[dict[str, Any]], dict[str, Any]],
        scenario_scene_prepare: Callable[[dict[str, Any], Any], dict[str, Any]],
    ) -> None:
        self.manager = manager
        self.players = players
        self.connections = connections
        self.scene_ready = scene_ready
        self.vehicle_world = vehicle_world
        self.world_map = world_map
        self.send = send
        self.save_result = save_result
        self.save_position = save_position
        self.world_scene_prepare = world_scene_prepare
        self.scenario_scene_prepare = scenario_scene_prepare

    async def send_events(self, events: list[ScenarioEvent]) -> None:
        for event in events:
            recipients = self._recipients(event)
            for player_id in recipients:
                websocket = self.connections.get(player_id)
                player = self.players.get(player_id)
                if websocket is None or player is None:
                    continue
                payload = self._event_payload(event, player)
                await self.send(websocket, payload)
            if event.type == "scenario_result" and event.session_id is not None:
                session = self.manager.sessions[event.session_id]
                for participant_id in session.participants:
                    player = self.players.get(participant_id)
                    if player is not None:
                        state = player["vehicle"]
                        player["scenarioFinish"] = (
                            state.x,
                            state.z,
                            state.heading,
                        )
                self._save_result(event)
                asyncio.create_task(self.return_from_scenario(event.session_id))

    def _recipients(self, event: ScenarioEvent) -> tuple[str, ...]:
        if event.player_id is not None:
            return (event.player_id,)
        if event.session_id is None:
            return ()
        session = self.manager.sessions.get(event.session_id)
        return tuple(session.participants) if session else ()

    def _event_payload(self, event: ScenarioEvent, player: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": event.type,
            "sceneId": player["sceneId"],
            "epoch": player["epoch"],
            "scenarioId": event.scenario_id,
        }
        for name in ("session_id", "waiting", "required", "role_id", "reason", "passed", "xp", "result_id"):
            value = getattr(event, name)
            if value is not None:
                payload[{"session_id": "sessionId", "role_id": "roleId", "result_id": "resultId"}.get(name, name)] = value
        if event.violation_ids:
            payload["violationIds"] = list(event.violation_ids)
        if event.type == "scenario_result" and event.session_id is not None:
            session = self.manager.sessions[event.session_id]
            payload["players"] = [
                {
                    "id": participant_id,
                    "roleId": role_id,
                    "passed": not session.violations.get(participant_id),
                    "violationIds": session.violations.get(participant_id, []),
                    "xp": session.xp.get(participant_id, 0),
                }
                for participant_id, role_id in session.participants.items()
            ]
        return payload

    def _save_result(self, event: ScenarioEvent) -> None:
        if event.session_id is None or event.result_id is None:
            raise RuntimeError("scenario result is missing identifiers")
        session = self.manager.sessions[event.session_id]
        for player_id, role_id in session.participants.items():
            self.save_result(
                event.result_id,
                session.id,
                session.definition.id,
                player_id,
                role_id,
                not session.violations.get(player_id),
                session.xp.get(player_id, 0),
                session.violations.get(player_id, []),
            )

    async def prepare_session(self, session_id: str) -> None:
        session = self.manager.sessions[session_id]
        session.state = ScenarioState.LOADING
        for participant_id, role_id in session.participants.items():
            player = self.players[participant_id]
            role = next(role for role in session.definition.roles if role.id == role_id)
            x, z, heading = role.spawn
            player["scenarioReturn"] = (
                player["vehicle"].x,
                player["vehicle"].z,
                player["vehicle"].heading,
            )
            player.update(
                sceneId=session.id,
                sceneKind="scenario",
                scenarioId=session.definition.id,
                roleId=role_id,
                scenarioSessionId=session.id,
                epoch=player["epoch"] + 1,
                vehicle=VehicleState(x=x, z=z, heading=heading),
                vertical=self.vehicle_world.restore(x, z, heading, self.world_map.get("spawnY", 0)),
                controls=Controls(brake=1),
                seq=0,
                applied_seq=0,
                input_time=0.0,
                previous_vehicle=(x, z, 0.0),
            )
            self.scene_ready.discard(participant_id)
            websocket = self.connections.get(participant_id)
            if websocket is not None:
                await self.send(websocket, self.scenario_scene_prepare(player, session))

    async def leave_to_return_spawn(self, player_id: str) -> None:
        player = self.players.get(player_id)
        if player is None or player.get("sceneKind") != "scenario":
            return
        session_id = player.get("scenarioSessionId")
        if session_id is not None:
            await self.cancel_session(session_id)

    async def cancel_session(
        self,
        session_id: str,
        exclude_player_id: str | None = None,
    ) -> None:
        session = self.manager.sessions.get(session_id)
        if session is None:
            return
        await self.send_events(self.manager.cancel(session_id, "participant_left"))
        x, z, heading = session.definition.return_spawn
        for participant_id in session.participants:
            if participant_id == exclude_player_id:
                continue
            player = self.players.get(participant_id)
            if player is None or player.get("sceneKind") != "scenario":
                continue
            self._move_to_world(player, x, z, heading)
            websocket = self.connections.get(participant_id)
            if websocket is not None:
                await self.send(websocket, self.world_scene_prepare(player))
        self.manager.discard(session_id)

    async def return_cancelled(self, session_id: str) -> None:
        session = self.manager.sessions.get(session_id)
        if session is None:
            return
        for participant_id in session.participants:
            player = self.players.get(participant_id)
            if player is None or player.get("sceneKind") != "scenario":
                continue
            x, z, heading = session.definition.return_spawn
            self._move_to_world(player, x, z, heading)
            websocket = self.connections.get(participant_id)
            if websocket is not None:
                await self.send(websocket, self.world_scene_prepare(player))
        self.manager.discard(session_id)

    async def return_from_scenario(self, session_id: str) -> None:
        await asyncio.sleep(5)
        session = self.manager.sessions.get(session_id)
        if session is None or session.state != ScenarioState.FINISHED:
            return
        participants = tuple(session.participants)
        self.manager.release(session_id)
        for participant_id in participants:
            player = self.players.get(participant_id)
            websocket = self.connections.get(participant_id)
            if player is None or websocket is None:
                continue
            x, z, heading = player.get(
                "scenarioFinish",
                (
                    player["vehicle"].x,
                    player["vehicle"].z,
                    player["vehicle"].heading,
                ),
            )
            player.update(
                sceneId="world:main",
                sceneKind="world",
                scenarioId=None,
                roleId=None,
                scenarioSessionId=None,
                epoch=player["epoch"] + 1,
                vehicle=VehicleState(x=x, z=z, heading=heading),
                vertical=self.vehicle_world.restore(x, z, heading, self.world_map.get("spawnY", 0)),
                controls=Controls(brake=1),
                seq=0,
                applied_seq=0,
                input_time=0.0,
                previous_vehicle=(x, z, 0.0),
            )
            self.save_position(
                participant_id,
                x,
                z,
                heading,
                player["vertical"].y,
                session.definition.map_id,
            )
            player.pop("scenarioReturn", None)
            player.pop("scenarioFinish", None)
            self.scene_ready.discard(participant_id)
            await self.send(websocket, self.world_scene_prepare(player))
        self.manager.discard(session_id)

    def _move_to_world(self, player: dict[str, Any], x: float, z: float, heading: float) -> None:
        body = self.vehicle_world.restore(
            x, z, heading, self.world_map.get("spawnY", 0)
        )
        player.update(
            sceneId="world:main",
            sceneKind="world",
            scenarioId=None,
            roleId=None,
            scenarioSessionId=None,
            epoch=player["epoch"] + 1,
            vehicle=VehicleState(x=x, z=z, heading=heading),
            vertical=body,
            controls=Controls(brake=1),
            seq=0,
            applied_seq=0,
            input_time=0.0,
            previous_vehicle=(x, z, 0.0),
        )
        player.pop("scenarioReturn", None)
        self.scene_ready.discard(player["id"])
        self.save_position(
            player["id"],
            x,
            z,
            heading,
            body.y,
            self.world_map["worldId"],
        )
