"""Факты проезда: непрерывные геометрические проверки и один отчёт на игрока."""
import json
import math
import uuid
from dataclasses import replace
from .world_physics import CAR_WIDTH, CAR_LENGTH, CAR_HEIGHT, penetration

CATEGORIES = ('roadMarkings', 'laneChanges', 'rightOfWay', 'trafficSigns', 'collisions')


def corners(state):
    c, s = math.cos(state.heading), math.sin(state.heading)
    return [(state.x+c*x+s*z, state.z-s*x+c*z)
            for x in (-CAR_WIDTH/2, CAR_WIDTH/2) for z in (-CAR_LENGTH/2, CAR_LENGTH/2)]


def intersects_line(state, line):
    (ax, az), (bx, bz) = line
    dx, dz = bx-ax, bz-az
    length = math.hypot(dx, dz)
    if length == 0:
        raise ValueError('Zero-length marking')
    box = dict(x=(ax+bx)/2, z=(az+bz)/2, heading=math.atan2(dx,dz),
               halfWidth=.025, halfLength=length/2)
    return bool(penetration(state.x,state.z,state.heading,box))


def samples(previous, current):
    angle = math.atan2(math.sin(current.heading-previous.heading), math.cos(current.heading-previous.heading))
    # Вращение тоже двигает углы кузова. Шаг ограничен 5 см.
    travel = math.hypot(current.x-previous.x,current.z-previous.z)+abs(angle)*CAR_LENGTH/2
    steps = max(1,math.ceil(travel/.05))
    for i in range(steps+1):
        t=i/steps
        yield replace(current,x=previous.x+(current.x-previous.x)*t,
                      z=previous.z+(current.z-previous.z)*t,heading=previous.heading+angle*t)


class PassageResults:
    def __init__(self, session_id, players, definition, now):
        self.session_id, self.definition, self.started = session_id, definition, now
        self.previous = {p['id']: p['vehicle'] for p in players}
        self.roles = {p['id']:p['roleId'] for p in players}
        self.events = {p['id']:[] for p in players}
        self.active = set()
        self.emitted = set()
        self.result_ids = {p['id']:str(uuid.uuid4()) for p in players}

    def event(self, player, category, rule, key, now, details, related=(), sign=None):
        token = (player['id'],category,key)
        if token not in self.active:
            self.events[player['id']].append(dict(
                id=str(uuid.uuid4()), category=category, ruleId=rule,
                timeMs=max(0,round((now-self.started)*1000)),
                position=dict(x=player['vehicle'].x,y=player['vertical'].y,z=player['vehicle'].z),
                relatedPlayerIds=list(related),signId=sign,details=details))
        self.active.add(token)
        return token

    def observe(self, players, now):
        current_active = set()
        rules = self.definition.get('rules', {})
        for player in players:
            pid=player['id']
            if pid in self.emitted:
                continue
            state=player['vehicle'];previous=self.previous[pid]
            path=list(samples(previous,state))
            def record(category,rule,key,details,related=(),sign=None):
                current_active.add(self.event(player,category,rule,key,now,details,related,sign))
            for marking in rules.get('markings',[]):
                if marking['crossingAllowed']:
                    continue
                if any(intersects_line(p,marking['line']) for p in path):
                    record('roadMarkings','forbidden-marking-crossing',marking['id'],'Пересечение запрещённой разметки')
            for lane in rules.get('laneZones',[]):
                if player['roleId'] not in lane['roles']:
                    continue
                zone=lane['zone'];allowed=lane['allowed']
                for p in path:
                    if zone[0] <= p.x <= zone[2] and zone[1] <= p.z <= zone[3]:
                        if any(not (allowed[0]-.05 <= x <= allowed[2]+.05 and allowed[1]-.05 <= z <= allowed[3]+.05) for x,z in corners(p)):
                            record('laneChanges','incorrect-lane',lane['id'],'Кузов вышел за границы разрешённой полосы')
                            break
            for sign in rules.get('signs',[]):
                if sign['kind'] == 'priority':
                    continue  # Приоритет проверяется отдельно, без двойного учёта.
                if sign['kind'] != 'speedLimit':
                    continue
                zone=sign['zone']
                if zone[0] <= state.x <= zone[2] and zone[1] <= state.z <= zone[3] and abs(state.speed) > sign['limitMps']+.1:
                    record('trafficSigns','speed-limit',sign['id'],'Превышение ограничения скорости',sign=sign['id'])
            for other in players:
                if other['id']==pid or other['id'] in self.emitted:
                    continue
                if other['id'] in player.get('contact_players',set()) or pid in other.get('contact_players',set()):
                    record('collisions','vehicle-contact',other['id'],'Столкновение с автомобилем',(other['id'],))
                if player['roleId'] != 'left-turn' or other['roleId'] != 'straight':
                    continue
                conflict=rules.get('conflict')
                if conflict and any(penetration(p.x,p.z,p.heading,conflict) for p in path):
                    b=other['vehicle']
                    # Встречный ещё не освободил область; прогнозируем время его подхода
                    # и время освобождения полосы поворачивающим автомобилем.
                    arrival=max(0,b.z-25.65)/max(abs(b.speed),.01)
                    clearing=max(0,state.x-55.3)/max(abs(state.speed),1)+.5
                    if b.z+CAR_LENGTH/2>19 and (penetration(b.x,b.z,b.heading,conflict) or b.speed>.5 and arrival<clearing):
                        record('rightOfWay','yield-to-oncoming','oncoming','Не уступили встречному автомобилю',(other['id'],))
            self.previous[pid]=state
        # Длительное нарушение даёт одно событие; после прекращения новое считается отдельно.
        self.active=current_active

    def finish(self, pid, status, now):
        if pid in self.emitted:
            return None
        self.emitted.add(pid)
        rules=self.definition.get('rules',{})
        coverage=rules.get('coverage',{})
        events=self.events[pid]
        report=dict(schemaVersion=1,resultId=self.result_ids[pid],sessionId=self.session_id,
                    scenario=dict(id=self.definition['id'],version=self.definition.get('version',1),type=self.definition.get('type','short')),
                    playerId=pid,roleId=self.roles[pid],status=status,durationMs=max(0,round((now-self.started)*1000)),
                    checks={category:dict(checked=coverage.get(category,False),
                            violationCount=sum(v['category']==category for v in events) if coverage.get(category,False) else None)
                            for category in CATEGORIES},violations=events)
        print(json.dumps(report,ensure_ascii=False,allow_nan=False),flush=True)
        return report
