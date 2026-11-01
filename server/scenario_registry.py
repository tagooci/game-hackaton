"""Local scenario registry, each scene uses geometry extracted from the world."""
import json
from pathlib import Path
from .world_physics import VehicleWorld

ROOT = Path(__file__).resolve().parent.parent / 'client/public/content/scenarios'
DEFINITIONS = {}
WORLDS = {}
for key in ('left-turn', 'equal-priority', 'roundabout', 'bridge-junction'):
    folder = ROOT / ('left-turn-v2' if key == 'left-turn' else key)
    definition = json.loads((folder / 'scenario.json').read_text(encoding='utf-8'))
    definition['spawns'] = [role['spawn'] for role in definition['roles']]
    definition['finishes'] = {role['id']:role['finish'] for role in definition['roles']}
    DEFINITIONS[key] = definition
    nav = json.loads((folder/'navigation.json').read_text(encoding='utf-8'))
    WORLDS[key] = VehicleWorld(nav['surfaces'], nav['colliders'], nav['ceilings'])

def definition_for(player):
    return DEFINITIONS[player.get('scenarioKey') or 'left-turn']

def world_for(player):
    return WORLDS[player.get('scenarioKey') or 'left-turn']


def body_at(world,pose):
    x,z,heading=(pose[k] for k in ('x','z','heading'))
    y=world.surface.sample(x,z,heading,.1)[0]
    return world.restore(x,z,heading,y)
