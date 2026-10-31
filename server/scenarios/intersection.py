"""Local scenario logic. The v2 host supplies physics, identity and scene epochs.

No client coordinates are accepted by this module. All times are monotonic
seconds supplied by the host, which makes the lifecycle deterministic in tests.
"""
from dataclasses import dataclass, field
from itertools import combinations
import json
import math
from pathlib import Path
import random
from uuid import uuid4


MAP_PATH = Path(__file__).resolve().parents[2] / 'client/public/scenarios/priority-01.json'


def load_definition(path=MAP_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'))


@dataclass(frozen=True)
class Pose:
    x: float
    z: float
    heading: float
    speed: float = 0.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.x, self.z, self.heading, self.speed)):
            raise ValueError('Pose must contain finite server numbers')


@dataclass(frozen=True)
class ReturnPoints:
    """World author supplies poses outside the activation trigger for EACH entry."""
    origin: Pose
    exits: dict[str, Pose]
    vehicle_type: str = 'car'

    def __post_init__(self):
        if set(self.exits) != {'north', 'east', 'south', 'west'}:
            raise ValueError('Four world return exits are required')


@dataclass
class Participant:
    player_id: str
    role: dict
    returns: ReturnPoints
    pose: Pose
    ready: bool = False
    entered: bool = False
    exit: str | None = None
    entry_peers: list = field(default_factory=list)


def corners(pose, length, width):
    forward = (math.sin(pose.heading), math.cos(pose.heading))
    right = (math.cos(pose.heading), -math.sin(pose.heading))
    return [(pose.x + a * length / 2 * forward[0] + b * width / 2 * right[0],
             pose.z + a * length / 2 * forward[1] + b * width / 2 * right[1])
            for a, b in ((1, 1), (1, -1), (-1, -1), (-1, 1))]


def overlapping(first, second):
    """Separating-axis test for two convex rectangles, including touching edges."""
    for polygon in (first, second):
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            axis = (a[1] - b[1], b[0] - a[0])
            p = [x * axis[0] + z * axis[1] for x, z in first]
            q = [x * axis[0] + z * axis[1] for x, z in second]
            if max(p) < min(q) or max(q) < min(p):
                return False
    return True


class IntersectionSession:
    def __init__(self, candidates, now, definition=None, rng=None):
        if len(candidates) not in (2, 3):
            raise ValueError('A scenario requires two or three players')
        self.definition = definition or load_definition()
        self.scene_id = f'scenario:{uuid4().hex}'
        roles = self.definition['roles'][:len(candidates)]
        roles = (rng or random.SystemRandom()).sample(roles, len(roles))
        self.participants = {
            pid: Participant(pid, role, returns, Pose(**role['spawn']))
            for (pid, returns), role in zip(candidates.items(), roles)
        }
        self.phase = 'loading'
        self.deadline = now + self.definition['loadingSeconds']
        self.start_at = None
        self.started_at = None
        self.result = None
        self.violations = []
        self.previous = {pid: p.pose for pid, p in self.participants.items()}
        self.result_at = None

    def mark_ready(self, player_id, scene_id, now):
        if scene_id != self.scene_id or self.phase != 'loading':
            return False
        if now >= self.deadline:
            self._finish('cancelled', 'loading_timeout', now)
            return False
        participant = self.participants.get(player_id)
        if not participant:
            return False
        participant.ready = True
        if all(p.ready for p in self.participants.values()):
            self.phase = 'countdown'
            self.start_at = now + self.definition['countdownSeconds']
        return True

    def _violation(self, player_id, rule_id, text):
        if any(v['playerId'] == player_id and v['ruleId'] == rule_id for v in self.violations):
            return
        self.violations.append({'eventId': uuid4().hex, 'playerId': player_id,
                                'ruleId': rule_id, 'severity': 'violation', 'text': text})

    def _finish(self, status, reason, now):
        if self.result is not None:
            return
        self.phase = 'cancelled' if status == 'cancelled' else 'finished'
        self.result_at = now
        self.result = {'resultId': uuid4().hex, 'sceneId': self.scene_id,
                       'status': status, 'reason': reason,
                       'violations': list(self.violations),
                       'participants': [
                           {'playerId': p.player_id, 'roleId': p.role['roleId'], 'exit': p.exit}
                           for p in self.participants.values()]}

    def disconnect(self, player_id, now):
        if player_id in self.participants:
            self._finish('cancelled', 'participant_disconnected', now)

    def fail_loading(self, player_id, now):
        if player_id in self.participants:
            self._finish('cancelled', 'loading_failed', now)

    def advance(self, now, states):
        """One fixed server tick AFTER physics; states is {playerId: Pose}."""
        if self.result is not None:
            return self.result
        if self.phase == 'loading':
            if now >= self.deadline:
                self._finish('cancelled', 'loading_timeout', now)
            return self.result
        if self.phase == 'countdown':
            if now < self.start_at:
                return None
            self.phase = 'running'
            self.started_at = self.start_at
        if now >= self.started_at + self.definition['durationSeconds']:
            self._finish('timeout', 'time_limit', now)
            return self.result

        for pid, pose in states.items():
            if pid in self.participants and not self.participants[pid].exit:
                self.participants[pid].pose = pose

        active = [p for p in self.participants.values() if not p.exit]
        # Subdivide authoritative movement to avoid missing crossing rectangles
        # between snapshots. Input speed/teleport validation belongs to physics.
        distance = max((math.hypot(p.pose.x - self.previous.get(p.player_id, p.pose).x,
                                   p.pose.z - self.previous.get(p.player_id, p.pose).z)
                        for p in active), default=0)
        steps = max(1, math.ceil(distance / .5))
        for step in range(1, steps + 1):
            polygons = {}
            for p in active:
                before = self.previous.get(p.player_id, Pose(**p.role['spawn']))
                t = step / steps
                angle = math.atan2(math.sin(p.pose.heading - before.heading),
                                   math.cos(p.pose.heading - before.heading))
                pose = Pose(before.x + (p.pose.x - before.x) * t,
                            before.z + (p.pose.z - before.z) * t, before.heading + angle * t)
                polygons[p.player_id] = corners(pose, p.role['length'], p.role['width'])
            for a, b in combinations(active, 2):
                if overlapping(polygons[a.player_id], polygons[b.player_id]):
                    self._finish('failed', 'collision', now)
                    return self.result

        half = self.definition['intersectionHalfSize']
        box = [(-half, -half), (half, -half), (half, half), (-half, half)]
        entering = []
        for p in active:
            if not p.entered and overlapping(corners(p.pose, p.role['length'], p.role['width']), box):
                entering.append(p)
                # Preserve the priority situation until the actual exit reveals
                # the manoeuvre; no client-provided turn intentions are trusted.
                p.entry_peers = [(q.player_id, q.role['entry'], q.role['vehicleType'])
                                 for q in active if q.player_id != p.player_id]
        for p in entering:
            p.entered = True
        for p in active:
            exit_name = self._exit(p)
            if p.entered and exit_name:
                p.exit = exit_name
                self._check_priority(p)
        self.previous = {p.player_id: p.pose for p in active}
        if all(p.exit for p in self.participants.values()):
            self._finish('failed' if self.violations else 'success',
                         'priority_violation' if self.violations else 'completed', now)
        return self.result

    def _exit(self, participant):
        pose = participant.pose
        distance = self.definition['finishDistance']
        road_half = self.definition['roadWidth'] / 2
        # Entire body must pass the finish line and point outwards. Sideways
        # shortcuts over grass cannot complete a scenario.
        footprint = corners(pose, participant.role['length'], participant.role['width'])
        candidates = {
            'north': all(z >= distance and abs(x) <= road_half for x, z in footprint),
            'south': all(z <= -distance and abs(x) <= road_half for x, z in footprint),
            'east': all(x >= distance and abs(z) <= road_half for x, z in footprint),
            'west': all(x <= -distance and abs(z) <= road_half for x, z in footprint),
        }
        for name, reached in candidates.items():
            heading = self.definition['exits'][name]['heading']
            if reached and math.cos(pose.heading - heading) > .7:
                if name == participant.role['entry']:
                    self._violation(participant.player_id, 'invalid_route', 'Возврат на исходную дорогу вместо проезда')
                return name
        return None

    def _check_priority(self, p):
        if p.role['vehicleType'] == 'tram':
            return
        order = ['south', 'east', 'north', 'west']
        entry = order.index(p.role['entry'])
        right_entry = order[(entry + 1) % 4]
        opposite_entry = order[(entry + 2) % 4]
        left_exit = order[(entry - 1) % 4]
        for _, peer_entry, vehicle in p.entry_peers:
            if vehicle == 'tram':
                self._violation(p.player_id, 'tram_priority', 'Не уступили трамваю на равнозначном перекрёстке')
            elif peer_entry == right_entry:
                self._violation(p.player_id, 'yield_right', 'Не уступили участнику справа')
            elif p.exit == left_exit and peer_entry == opposite_entry:
                self._violation(p.player_id, 'yield_on_left_turn', 'При левом повороте не уступили встречному участнику')

    def return_pose(self, player_id):
        if self.result is None:
            raise RuntimeError('Scenario has not ended')
        p = self.participants[player_id]
        return p.returns.exits[p.exit] if self.result['status'] == 'success' and p.exit else p.returns.origin


class ScenarioQueue:
    """Host checks trigger occupancy and Enter consent before enqueueing."""
    def __init__(self, definition=None):
        self.definition = definition or load_definition()
        self.waiting = {}
        self.deadline = None

    def join(self, player_id, returns, now):
        if player_id not in self.waiting:
            if len(self.waiting) == 3:
                return False
            self.waiting[player_id] = returns
        if len(self.waiting) >= 2 and self.deadline is None:
            self.deadline = now + self.definition['queueSeconds']
        return True

    def leave(self, player_id):
        self.waiting.pop(player_id, None)
        if len(self.waiting) < 2:
            self.deadline = None

    def advance(self, now, rng=None):
        if self.deadline is None or now < self.deadline or len(self.waiting) < 2:
            return None
        session = IntersectionSession(self.waiting, now, self.definition, rng)
        self.waiting = {}
        self.deadline = None
        return session
