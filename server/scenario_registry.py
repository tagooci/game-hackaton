"""Local scenario registry, each scene uses geometry extracted from the world."""
import json
from pathlib import Path
from .world_physics import VehicleWorld

ROOT = Path(__file__).resolve().parent.parent / 'client/public/content/scenarios'
DEFINITIONS = {}
WORLDS = {}
for key in ('left-turn', 'equal-priority', 'roundabout'):
    folder = ROOT / key
    definition = json.loads((folder / 'scenario.json').read_text(encoding='utf-8'))
    if key == 'left-turn':
        definition.update(title='Левый поворот', number=1, requiredPlayers=2, timeLimitSeconds=90,
                          center=[60,20], roleIds=['left-turn','straight'],
                          roles=[dict(id='left-turn',description='Поверните налево и остановитесь у своей арки.',spawn=definition['spawns'][0],finish=definition['finishes']['left-turn']),
                                 dict(id='straight',description='Проедьте прямо и остановитесь у своей арки.',spawn=definition['spawns'][1],finish=definition['finishes']['straight'])])
    definition['spawns'] = [role['spawn'] for role in definition['roles']]
    definition['finishes'] = {role['id']:role['finish'] for role in definition['roles']}
    DEFINITIONS[key] = definition
    nav = json.loads((folder/'navigation.json').read_text(encoding='utf-8'))
    WORLDS[key] = VehicleWorld(nav['surfaces'], nav['colliders'], nav['ceilings'])

def definition_for(player):
    return DEFINITIONS[player.get('scenarioKey') or 'left-turn']

def world_for(player):
    return WORLDS[player.get('scenarioKey') or 'left-turn']
