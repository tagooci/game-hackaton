from __future__ import annotations

from typing import Dict

from fastapi import WebSocket


players: dict[str, dict] = {}
SPAWN_X = 0
SPAWN_Z = 0
next_id = 1


def make_id() -> str:
    global next_id
    player_id = next_id
    next_id += 1
    return f"p{player_id}"


def add_player(ws: WebSocket, name: str) -> Dict:
    player_id = make_id()
    state = {
        "id": player_id,
        "ws": ws,
        "name": name,
        "zone": "world",
        "x": SPAWN_X,
        "z": SPAWN_Z,
        "heading": 0,
    }
    players[player_id] = state
    return state


def public_view(player: Dict) -> Dict:
    return {
        "id": player["id"],
        "name": player["name"],
        "zone": player["zone"],
        "x": player["x"],
        "z": player["z"],
        "heading": player["heading"],
    }


def others_view(exclude_id: str | None = None) -> list[Dict]:
    return [public_view(p) for p in players.values() if p["id"] != exclude_id]


def remove_player(player_id: str) -> None:
    players.pop(player_id, None)


def snapshot_view(zone: str) -> list[Dict]:
    return [
        {"id": p["id"], "x": p["x"], "z": p["z"], "heading": p["heading"]}
        for p in players.values()
        if p["zone"] == zone
    ]
