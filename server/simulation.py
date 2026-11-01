"""Background loops for vehicle simulation and snapshot delivery."""

import asyncio
from typing import Any

from .app_helpers import player_snapshot, send
from .vehicle import Controls, VehicleConfig, step_vehicle


async def run_physics(
    players: dict[str, dict[str, Any]],
    scene_ready: set[str],
    vehicle_world: Any,
    vehicle_config: VehicleConfig,
    scenario_observe: Any,
    get_tick: Any,
) -> None:
    dt = 1 / 30
    loop = asyncio.get_running_loop()
    deadline = loop.time()
    while True:
        deadline += dt
        await asyncio.sleep(max(0, deadline - loop.time()))
        now = loop.time()
        if now - deadline > 0.2:
            deadline = now
        for player in players.values():
            if "vehicle" not in player:
                continue
            if player["id"] not in scene_ready or get_tick() < player.get("start_tick", 0):
                continue
            controls = (
                player["controls"]
                if now - player["input_time"] <= 0.25
                else Controls(brake=1)
            )
            previous = player.get(
                "previous_vehicle",
                (player["vehicle"].x, player["vehicle"].z, player["vehicle"].speed),
            )
            state = step_vehicle(player["vehicle"], controls, vehicle_config, dt)
            if player.get("v2"):
                others = [
                    vehicle_world.car_box(other["vehicle"], other["vertical"])
                    for other in players.values()
                    if other["id"] != player["id"]
                    and other["id"] in scene_ready
                    and other["sceneId"] == player["sceneId"]
                ]
                state, player["vertical"] = vehicle_world.step(
                    player["vehicle"], state, player["vertical"], dt, others
                )
            player["vehicle"] = state
            player["applied_seq"] = player.get("seq", 0)
            player.update(
                x=round(state.x, 2),
                z=round(state.z, 2),
                heading=round(state.heading, 2),
            )
            player["previous_vehicle"] = (state.x, state.z, state.speed)
            await scenario_observe(
                player["id"],
                previous,
                (state.x, state.z, state.speed),
                now,
            )


async def run_snapshots(
    legacy_players: dict[str, dict[str, Any]],
    players: dict[str, dict[str, Any]],
    connections: dict[str, Any],
    scene_ready: set[str],
    vehicle_config: VehicleConfig,
    snapshot_view: Any,
    send_message: Any,
    tick_rate: int,
    get_tick: Any,
) -> None:
    while True:
        await asyncio.sleep(1 / tick_rate)
        tick = get_tick()
        for player in list(legacy_players.values()):
            await send_message(player["ws"], {
                "type": "snapshot",
                "tick": tick,
                "players": snapshot_view(player["zone"]),
            })
        for player_id, ws in list(connections.items()):
            if player_id not in scene_ready:
                continue
            await send_message(ws, {
                "type": "snapshot",
                "sceneId": players[player_id]["sceneId"],
                "epoch": players[player_id]["epoch"],
                "tick": tick,
                "players": [
                    player_snapshot(players[pid], vehicle_config)
                    for pid in players
                    if pid in scene_ready
                    and players[pid]["sceneId"] == players[player_id]["sceneId"]
                ],
                "signals": [],
            })
