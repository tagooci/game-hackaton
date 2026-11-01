"""Two independent, slow clockwise lane loops in the shared world only."""
from bisect import bisect_right
from dataclasses import dataclass, replace
import math

from .vehicle import VehicleState, approach
from .world_physics import VerticalState, penetration

CRUISE_SPEED = 3.0  # m/s, approximately 11 km/h
BRAKING = 5.0
LANE_OFFSET = 1.7  # right side of the road, with room for the full vehicle body


class LaneLoop:
    """Four-node directed cycle with rounded right turns, no route branching."""
    def __init__(self, west, east, south, north):
        self.nodes = ((west, south), (west, north), (east, north), (east, south))
        radius = 5 - LANE_OFFSET
        corners = ((west+5, north-5, math.pi), (east-5, north-5, math.pi/2),
                   (east-5, south+5, 0), (west+5, south+5, -math.pi/2))
        self.points = []
        for x, z, angle in corners:
            for i in range(25):
                a = angle - i * math.pi / 48
                self.points.append((x + radius*math.cos(a), z + radius*math.sin(a)))
        self.points.append(self.points[0])
        self.lengths = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.lengths.append(self.lengths[-1] + math.dist(a, b))
        self.length = self.lengths[-1]

    def pose(self, distance, speed=0):
        distance %= self.length
        index = min(bisect_right(self.lengths, distance)-1, len(self.points)-2)
        a, b = self.points[index:index+2]
        t = (distance-self.lengths[index])/(self.lengths[index+1]-self.lengths[index])
        return VehicleState(a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t,
                            math.atan2(b[0]-a[0], b[1]-a[1]), speed)


def overlaps(a, b, margin=0):
    if a['minY'] >= b['maxY'] or b['minY'] >= a['maxY']:
        return False
    # penetration() uses the same own-car dimensions as the player physics.
    expanded = {**b, 'halfWidth': b['halfWidth']+margin,
                'halfLength': b['halfLength']+margin}
    return penetration(a['x'], a['z'], a['heading'], expanded) is not None


@dataclass
class TrafficCar:
    id: str
    route: LaneLoop
    distance: float
    vehicle: VehicleState
    vertical: VerticalState
    color: int
    waiting: float = 0


class NpcTraffic:
    def __init__(self, world):
        self.world = world
        self.cars = []
        # Neither loop crosses another loop or any scenario gathering zone.
        for index, (south, north) in enumerate(((20, 50), (-70, -40))):
            route = LaneLoop(-60, -30, south, north)
            distance = route.length * 0.2
            state = route.pose(distance)
            y, _ = world.surface.sample(state.x, state.z, state.heading, .1)
            body = world.restore(state.x, state.z, state.heading, y)
            self.cars.append(TrafficCar(f'npc:traffic:{index+1}', route, distance, state, body, index))

    def boxes(self):
        return [{**self.world.car_box(car.vehicle, car.vertical), 'playerId': car.id}
                for car in self.cars]

    def _blocked_ahead(self, car, players):
        if not players:
            return False
        # Check the whole braking corridor, including predicted crossing traffic.
        horizon = max(8, car.vehicle.speed**2/(2*BRAKING)+5)
        for step in range(int(horizon/.5)+1):
            distance = step*.5
            future = car.route.pose(car.distance+distance)
            box = self.world.car_box(future, car.vertical)
            eta = min(3, distance/max(car.vehicle.speed, 1.5))
            for player in players:
                state, body = player['vehicle'], player['vertical']
                obstacle = self.world.car_box(state, body)
                obstacle['halfLength'] += 1.2  # bumper clearance, also at rest
                if overlaps(box, obstacle, .25):
                    return True
                predicted = {**obstacle,
                             'x': state.x+math.sin(state.heading)*state.speed*eta,
                             'z': state.z+math.cos(state.heading)*state.speed*eta}
                if overlaps(box, predicted, .4):
                    return True
        return False

    def step(self, dt, players=()):
        if not math.isfinite(dt) or not 0 < dt <= .1:
            raise ValueError('Invalid NPC timestep')
        players = list(players)
        player_boxes = [{**self.world.car_box(p['vehicle'], p['vertical']), 'playerId': p['id']}
                        for p in players]
        for car in self.cars:
            target = 0 if self._blocked_ahead(car, players) else CRUISE_SPEED
            speed = approach(car.vehicle.speed, target, (BRAKING if target == 0 else 1.2)*dt)
            travel = (car.vehicle.speed+speed)*.5*dt
            obstacles = player_boxes + [box for box in self.boxes() if box['playerId'] != car.id]
            # A swept safety envelope prevents the NPC from driving into a user
            # even if the user changes direction inside the prediction horizon.
            safe = True
            steps = max(1, math.ceil(travel/.1))
            for i in range(1, steps+1):
                candidate = car.route.pose(car.distance+travel*i/steps, speed)
                if any(overlaps(self.world.car_box(candidate, car.vertical), b, .12) for b in obstacles):
                    safe = False
                    break
            if not safe:
                car.vehicle = replace(car.vehicle, speed=0)
                car.waiting += dt
                continue
            proposed = car.route.pose(car.distance+travel, speed)
            state, body = self.world.step(car.vehicle, proposed, car.vertical, dt, obstacles)
            # Never drift off the fixed lane or teleport back after a collision.
            if math.hypot(state.x-proposed.x, state.z-proposed.z) > .01 or not body.grounded:
                car.vehicle = replace(car.vehicle, speed=0)
                continue
            car.distance = (car.distance+travel) % car.route.length
            car.vehicle, car.vertical = state, body
            car.waiting = car.waiting+dt if target == 0 and speed < .2 else 0

    def snapshots(self):
        result = []
        for car in self.cars:
            state = car.vehicle
            future = car.route.pose(car.distance+.5)
            turn = math.atan2(math.sin(future.heading-state.heading), math.cos(future.heading-state.heading))
            result.append(dict(id=car.id, name=f'NPC {car.color+1}', npc=True,
                               trafficMessage='Пропустите, пожалуйста' if car.waiting >= 5 else None,
                               vehicleType='car', color=car.color, x=round(state.x, 3), z=round(state.z, 3),
                               heading=state.heading, speed=state.speed, steering=0, lastInputSeq=0,
                               y=car.vertical.y, pitch=car.vertical.pitch, grounded=car.vertical.grounded,
                               throttle=.2 if state.speed > .1 else 0,
                               wheelAngle=math.atan(1.95*turn/.5)))
        return result
