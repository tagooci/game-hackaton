"""Built-in scenario definitions for the current world."""

import math
from typing import Any

from .scenario_model import ScenarioDefinition, ScenarioRole, ScenarioZone


def build_scenarios(world_map: dict[str, Any]) -> tuple[ScenarioDefinition, ...]:
    return (
        ScenarioDefinition(
            id="priority-test",
            map_id=world_map["worldId"],
            zone=ScenarioZone("junction-waiting", 56.0, 61.0, 36.0, 44.0),
            return_spawn=(60.0, 20.0, 0.0),
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
    )
