from __future__ import annotations

import time
from typing import Any

from fastapi import WebSocket

from .vehicle import Controls, VehicleState


v2_connections: dict[str, WebSocket] = {}
v2_scene_ready: set[str] = set()
v2_players: dict[str, dict[str, Any]] = {}


def create_v2_player(
    player_id: str,
    name: str,
    websocket: WebSocket,
    saved_state: tuple[float, float, float],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    x, z, heading = saved_state
    old_vehicle = previous["vehicle"] if previous else None
    vehicle = old_vehicle or VehicleState(x=x, z=z, heading=heading)
    return {
        "id": player_id,
        "name": name,
        "ws": websocket,
        "vehicle": VehicleState(vehicle.x, vehicle.z, vehicle.heading),
        "controls": Controls(brake=1),
        "seq": 0,
        "input_time": time.monotonic(),
        "color": previous["color"] if previous else None,
    }


def mark_scene_ready(player_id: str, start_tick: int) -> None:
    v2_scene_ready.add(player_id)
    v2_players[player_id]["start_tick"] = start_tick


def remove_v2_player(player_id: str, player: dict[str, Any]) -> None:
    if v2_players.get(player_id) is player:
        v2_players.pop(player_id, None)
    v2_scene_ready.discard(player_id)


def clear_v2_state() -> None:
    v2_connections.clear()
    v2_scene_ready.clear()
    v2_players.clear()
