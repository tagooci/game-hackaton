"""Small, server-authoritative LAN test host; NOT the production v2 runtime."""
from dataclasses import dataclass
import math
from uuid import uuid4

from .intersection import Pose, ReturnPoints, ScenarioQueue, load_definition


@dataclass
class Driver:
    name: str
    pose: Pose
    sequence: int = 0
    throttle: float = 0
    steering: float = 0
    brake: float = 1
    input_at: float = -math.inf


def step(pose, controls, role, dt):
    """Test-only arcade physics. Called at 30 Hz, never once per input packet."""
    throttle, steering, brake = controls
    speed = pose.speed
    acceleration = 2 if role['vehicleType'] != 'car' else 3.5
    if brake or not throttle:
        deceleration = 7 if brake else 1
        speed = math.copysign(max(0, abs(speed) - deceleration * dt), speed)
    else:
        speed += throttle * acceleration * dt
    speed = max(-3, min(8, speed))
    heading = pose.heading
    if role['vehicleType'] != 'tram':
        heading += speed / max(2.7, role['length'] * .55) * math.tan(steering * .5) * dt
    heading = (heading + math.pi) % (2 * math.pi) - math.pi
    return Pose(pose.x + math.sin(heading) * speed * dt,
                pose.z + math.cos(heading) * speed * dt, heading, speed)


class LanRoom:
    def __init__(self, store=None, definition=None):
        self.definition = definition or load_definition()
        self.queue = ScenarioQueue(self.definition)
        self.drivers = {}
        self.session = None
        self.store = store
        self.tick = 0
        self.last_result = None
        self.returned = {}
        self.saved_result_id = None

    def connect(self, name):
        if len(self.drivers) >= 3:
            return None
        pid = uuid4().hex
        self.drivers[pid] = Driver(name.strip()[:24] or 'Игрок', Pose(-12 + 6 * len(self.drivers), -35, 0))
        return pid

    def disconnect(self, pid, now):
        self.queue.leave(pid)
        if self.session:
            self.session.disconnect(pid, now)
        self.drivers.pop(pid, None)
        self.returned.pop(pid, None)

    def join_queue(self, pid, now):
        if pid not in self.drivers or self.session is not None:
            return False
        origin = self.drivers[pid].pose
        returns = ReturnPoints(origin, {
            'north': Pose(3.5, 40, 0), 'east': Pose(40, -3.5, math.pi / 2),
            'south': Pose(-3.5, -40, -math.pi), 'west': Pose(-40, 3.5, -math.pi / 2),
        })
        return self.queue.join(pid, returns, now)

    def ready(self, pid, scene_id, now):
        return self.session is not None and self.session.mark_ready(pid, scene_id, now)

    def input(self, pid, message, now):
        session = self.session
        if not session or session.phase != 'running' or session.result or pid not in session.participants:
            return False
        if message.get('sceneId') != session.scene_id:
            return False
        driver = self.drivers[pid]
        seq = message.get('seq')
        if type(seq) is not int or not 0 < seq <= 9007199254740991 or seq <= driver.sequence:
            return False
        values = [message.get(key) for key in ('throttle', 'steering', 'brake')]
        if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
            return False
        if not (-1 <= values[0] <= 1 and -1 <= values[1] <= 1 and 0 <= values[2] <= 1):
            return False
        driver.sequence = seq
        driver.throttle, driver.steering, driver.brake = values
        driver.input_at = now
        return True

    def advance(self, now, dt=1 / 30):
        self.tick += 1
        if self.session is None:
            self.session = self.queue.advance(now)
            if self.session:
                self.last_result = None
                self.returned = {}
                for pid, p in self.session.participants.items():
                    driver = self.drivers[pid]
                    driver.pose = p.pose
                    driver.sequence = 0
                    driver.input_at = -math.inf
            return
        session = self.session
        # Advance countdown before allowing movement, so the first running tick
        # starts from the exact role spawn for everyone.
        if session.phase != 'running' or session.result:
            session.advance(now, {})
        else:
            states = {}
            for pid, p in session.participants.items():
                if pid not in self.drivers or p.exit:
                    continue
                driver = self.drivers[pid]
                controls = (driver.throttle, driver.steering, driver.brake)
                if now - driver.input_at > .25:
                    controls = (0, 0, 1)
                next_pose = step(driver.pose, controls, p.role, dt)
                # Minimal road corridor; prevent leaving the map into empty space.
                half = self.definition['roadWidth'] / 2
                if abs(next_pose.x) > 47 or abs(next_pose.z) > 47 or (abs(next_pose.x) > half and abs(next_pose.z) > half):
                    next_pose = Pose(driver.pose.x, driver.pose.z, driver.pose.heading, 0)
                states[pid] = next_pose
                driver.pose = next_pose
            session.advance(now, states)
        if session.result:
            self.last_result = session.result
            if self.store and self.saved_result_id != session.result['resultId']:
                self.store.save(session.result)
                self.saved_result_id = session.result['resultId']
            if now >= session.result_at + self.definition['resultSeconds']:
                for pid in session.participants:
                    if pid in self.drivers:
                        pose = session.return_pose(pid)
                        self.drivers[pid].pose = Pose(pose.x, pose.z, pose.heading)
                        self.drivers[pid].input_at = -math.inf
                        self.returned[pid] = {'x': pose.x, 'z': pose.z, 'heading': pose.heading}
                self.session = None

    def snapshot(self, pid, now):
        session = self.session
        # A third connection arriving after roster lock waits in its own lobby.
        in_session = session is not None and pid in session.participants
        phase = session.phase if in_session else 'lobby'
        countdown = 0
        if in_session:
            until = session.start_at if phase == 'countdown' else session.deadline
            countdown = max(0, math.ceil((until or now) - now))
        elif self.queue.deadline:
            countdown = max(0, math.ceil(self.queue.deadline - now))
        players = []
        for other_id, driver in self.drivers.items():
            if in_session and other_id not in session.participants:
                continue
            if not in_session and session and other_id in session.participants:
                continue
            role = session.participants[other_id].role if in_session else self.definition['roles'][0]
            p = driver.pose
            players.append({'id': other_id, 'name': driver.name, 'roleId': role['roleId'],
                            'vehicleType': role['vehicleType'], 'x': round(p.x, 3), 'z': round(p.z, 3),
                            'heading': round(p.heading, 3), 'speed': round(p.speed, 3),
                            'finished': bool(in_session and session.participants[other_id].exit)})
        remaining = 90
        if in_session and session.started_at is not None:
            remaining = max(0, math.ceil(session.started_at + self.definition['durationSeconds'] - now))
        return {'type': 'lab_snapshot', 'tick': self.tick, 'playerId': pid,
                'sceneId': session.scene_id if in_session else 'lab:lobby', 'phase': phase,
                'busy': session is not None and not in_session,
                'players': players, 'queued': pid in self.queue.waiting, 'waiting': len(self.queue.waiting),
                'countdown': countdown, 'remaining': remaining,
                'result': session.result if in_session else self.last_result,
                'returned': self.returned.get(pid)}
