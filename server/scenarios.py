"""Подбор участников и проверка учебного левого поворота."""
import json
import math
import uuid
from pathlib import Path
from .vehicle import Controls, VehicleState
from .passage_results import PassageResults
from .world_physics import VehicleWorld, CAR_WIDTH, CAR_LENGTH, CAR_HEIGHT, penetration

CONTENT = Path(__file__).resolve().parent.parent / 'client/public/content/scenarios/left-turn'
SCENARIO = json.loads((CONTENT / 'scenario.json').read_text())
NAVIGATION = json.loads((CONTENT / 'navigation.json').read_text())
WORLD = VehicleWorld(NAVIGATION['surfaces'], NAVIGATION['colliders'], NAVIGATION['ceilings'])


def waiting(player):
    state, body = player['vehicle'], player['vertical']
    zone = SCENARIO['trigger']
    dx = abs(math.cos(state.heading))*CAR_WIDTH/2 + abs(math.sin(state.heading))*CAR_LENGTH/2
    dz = abs(math.sin(state.heading))*CAR_WIDTH/2 + abs(math.cos(state.heading))*CAR_LENGTH/2
    return (abs(state.speed) <= .5 and body.grounded
            and zone['minX'] <= state.x-dx and state.x+dx <= zone['maxX']
            and zone['minZ'] <= state.z-dz and state.z+dz <= zone['maxZ']
            and zone['minY'] <= body.y and body.y+CAR_HEIGHT <= zone['maxY'])



class ScenarioSessions:
    def __init__(self):
        self.waiters = {}
        self.sessions = {}
        self.count = 0
        self.pair_since = None

    async def update(self, players, ready, now, move, prepare):
        for scene_id, session in list(self.sessions.items()):
            active = [pid for pid in session['players'] if pid not in session.get('finished', set())]
            if any(pid not in players or players[pid]['sceneId'] != scene_id for pid in active) or (not session['started'] and now > session['deadline']):
                if session.get('results'):
                    for pid in active:
                        session['results'].finish(pid, 'cancelled', now)
                del self.sessions[scene_id]
                for pid in active:
                    if pid in players and players[pid]['sceneId'] == scene_id:
                        await move(players[pid], None, None)
            elif session['started']:
                if not session.get('results'):
                    session['results'] = PassageResults(scene_id, [players[pid] for pid in active], SCENARIO, now)
                session['results'].observe([players[pid] for pid in active], now)
                for pid in active:
                    player = players[pid]
                    state, body = player['vehicle'], player['vertical']
                    finish = SCENARIO['finishes'][player['roleId']]
                    dx, dz = state.x-finish['x'], state.z-finish['z']
                    angle = finish['heading']
                    stopped = (abs(dx*math.cos(angle)-dz*math.sin(angle)) <= .6
                               and abs(dx*math.sin(angle)+dz*math.cos(angle)) <= 1.5
                               and abs(state.speed) <= .5 and body.grounded
                               and math.cos(state.heading-angle) > .8)
                    timers = session.setdefault('finish_times', {})
                    if not stopped:
                        timers.pop(pid, None)
                        continue
                    timers.setdefault(pid, now)
                    if now-timers[pid] >= 1:
                        session['results'].finish(pid, 'completed', now)
                        session.setdefault('finished', set()).add(pid)
                        # Сцена сохраняет координаты общей карты: возвращаем на тот же выезд.
                        player['return_state'] = (state, body)
                        await move(player, None, None)
                if len(session.get('finished', set())) == len(session['players']):
                    del self.sessions[scene_id]
        for pid in list(self.waiters):
            if pid not in players or pid not in ready or players[pid]['sceneKind'] != 'world' or not waiting(players[pid]):
                self.waiters.pop(pid, None)
        for pid, player in players.items():
            if pid in ready and player['sceneKind'] == 'world' and waiting(player):
                self.waiters.setdefault(pid, now)
        candidates = sorted((time, pid) for pid, time in self.waiters.items() if now-time >= 1)
        self.count = min(2, len(candidates))
        if len(candidates) < 2:
            self.pair_since = None
            return
        if self.pair_since is None:
            self.pair_since = now
        if now - self.pair_since < .5:
            return
        self.pair_since = None
        while len(candidates) >= 2:
            pair, candidates = candidates[:2], candidates[2:]
            scene_id = f'scenario:left-turn:{uuid.uuid4()}'
            self.sessions[scene_id] = dict(players=[pid for _, pid in pair], deadline=now+30, started=False)
            for role, (_, pid) in enumerate(pair):
                self.waiters.pop(pid, None)
                await move(players[pid], scene_id, role)
            for _, pid in pair:
                await prepare(players[pid])

    def start(self, scene_id, ready):
        session = self.sessions[scene_id]
        if session['started'] or not all(pid in ready for pid in session['players']):
            return []
        session['started'] = True
        return session['players']
