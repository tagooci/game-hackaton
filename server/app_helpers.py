import json
"""Shared HTTP, WebSocket, and serialization helpers for the server app."""

import math
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse

from .vehicle import VehicleConfig, steering_angle


async def send(ws: WebSocket, data: dict[str, Any]) -> bool:
    try:
        await ws.send_json(data)
        return True
    except Exception:
        return False


async def send_error(ws: WebSocket, code: str, text: str) -> None:
    await send(ws, {"type": "error", "code": code, "text": text})


async def send_v2_error(ws: WebSocket, code: str, text: str) -> None:
    await send_error(ws, code, text)


async def broadcast(
    players: dict[str, dict[str, Any]],
    data: dict[str, Any],
    exclude_id: str | None = None,
) -> None:
    for player in list(players.values()):
        if player["id"] != exclude_id:
            await send(player["ws"], data)


def is_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


async def read_json_object(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="expected JSON object") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="expected JSON object")
    return body


def credentials(body: dict[str, Any]) -> tuple[str, str]:
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise HTTPException(
            status_code=400, detail="username and password are required"
        )
    return username, password


def session_response(
    account: dict[str, Any],
    token: str,
    session_cookie: str,
) -> JSONResponse:
    result = JSONResponse(
        {"playerId": account["playerId"], "name": account["name"]}
    )
    result.set_cookie(
        session_cookie,
        token,
        httponly=True,
        samesite="lax",
        secure=os.getenv("GAME_COOKIE_SECURE", "").lower() == "true",
        path="/",
    )
    return result


def world_resources(project_root: Path) -> list[dict[str, Any]]:
    manifest = json.loads((project_root / "client/public/content/world/manifest.json").read_text())
    return manifest["residentResources"]


def player_snapshot(
    player: dict[str, Any],
    vehicle_config: VehicleConfig,
) -> dict[str, Any]:
    state = player["vehicle"]
    return {
        "id": player["id"],
        "name": player["name"],
        "vehicleType": player.get("vehicleType", "car"),
        "roleId": player.get("roleId"),
        **{
            key: round(getattr(state, key), 3)
            for key in ("x", "z", "heading", "speed", "steering")
        },
        "lastInputSeq": player.get("applied_seq", 0),
        "y": round(player["vertical"].y, 4),
        "pitch": round(player["vertical"].pitch, 4),
        "wheelAngle": round(
            steering_angle(state.speed, state.steering, vehicle_config), 4
        ),
        "color": player["color"],
    }
