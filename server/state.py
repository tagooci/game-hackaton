from __future__ import annotations

import time
from typing import Any

from fastapi import WebSocket

from .vehicle import Controls, VehicleState


players: dict[str, dict] = {}
SPAWN_X = 0
SPAWN_Z = 0
next_id = 1

v2_connections: dict[str, WebSocket] = {}
v2_scene_ready: set[str] = set()
v2_players: dict[str, dict[str, Any]] = {}


def make_id() -> str:
    global next_id
    player_id = next_id
    next_id += 1
    return f"p{player_id}"


def add_player(websocket: WebSocket, name: str) -> dict:
    player_id = make_id()
    player = {
        "id": player_id,
        "ws": websocket,
        "name": name,
        "zone": "world",
        "x": SPAWN_X,
        "z": SPAWN_Z,
        "heading": 0,
    }
    players[player_id] = player
    return player


def public_view(player: dict) -> dict:
    return {
        "id": player["id"],
        "name": player["name"],
        "zone": player["zone"],
        "x": player["x"],
        "z": player["z"],
        "heading": player["heading"],
    }


def others_view(exclude_id: str | None = None) -> list[dict]:
    return [public_view(player) for player in players.values() if player["id"] != exclude_id]


def remove_player(player_id: str) -> None:
    players.pop(player_id, None)


def snapshot_view(zone: str) -> list[dict]:
    return [
        {"id": player["id"], "x": player["x"], "z": player["z"], "heading": player["heading"]}
        for player in players.values()
        if player["zone"] == zone
    ]


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
