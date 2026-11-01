"""Independent multiplayer queues and scene lifecycle for all local scenarios."""
import math
import secrets
from .scenario_registry import DEFINITIONS, WORLDS
from .local_scenario_rules import check_new_passage, finished_route
from .world_physics import CAR_WIDTH, CAR_LENGTH, CAR_HEIGHT

# Compatibility for imports that still describe the original scenario.
SCENARIO=DEFINITIONS['left-turn']
WORLD=WORLDS['left-turn']


def waiting(player, definition=SCENARIO):
    state,body=player['vehicle'],player['vertical'];zone=definition['trigger']
    dx=abs(math.cos(state.heading))*CAR_WIDTH/2+abs(math.sin(state.heading))*CAR_LENGTH/2
    dz=abs(math.sin(state.heading))*CAR_WIDTH/2+abs(math.cos(state.heading))*CAR_LENGTH/2
    road_contact=any(abs(y-body.y)<.08 for y,_ in WORLDS[definition['id']].surface.contacts(state.x,state.z,state.heading))
    return (abs(state.speed)<=.5 and body.grounded and road_contact
            and zone['minX']<=state.x-dx and state.x+dx<=zone['maxX']
            and zone['minZ']<=state.z-dz and state.z+dz<=zone['maxZ']
            and zone['minY']<=body.y and body.y+CAR_HEIGHT<=zone['maxY'])


class ScenarioSessions:
    def __init__(self):
        self.waiters={key:{} for key in DEFINITIONS}
        self.sessions={};self.counter=0;self.pair_since={};self.now=0.

    @property
    def count(self):return min(DEFINITIONS['left-turn']['requiredPlayers'],len(self.waiters['left-turn']))

    def queues(self):
        return [dict(id=key,title=d['title'],number=d['number'],required=d['requiredPlayers'],count=min(len(self.waiters[key]),d['requiredPlayers']),x=d.get('queuePoint',d['center'])[0],y=5,z=d.get('queuePoint',d['center'])[1]) for key,d in DEFINITIONS.items()]

    def queue_for(self,player):
        state=player['vehicle']
        return min(self.queues(),key=lambda q:math.hypot(state.x-q['x'],state.z-q['z']))

    async def update(self,players,ready,now,move,prepare):
        self.now=now
        for scene_id,session in list(self.sessions.items()):
            definition=DEFINITIONS[session['scenarioKey']]
            active=[pid for pid in session['players'] if pid not in session['finished']]
            missing=any(pid not in players or players[pid]['sceneId']!=scene_id for pid in active)
            load_timeout=not session['started'] and now>session['deadline']
            run_timeout=session['started'] and now>session['deadline']
            if missing or load_timeout or run_timeout:
                del self.sessions[scene_id]
                for pid in active:
                    if pid in players and players[pid]['sceneId']==scene_id:
                        player=players[pid]
                        if run_timeout:
                            previous=player.get('scenario_result')
                            player['scenario_result']=(previous+'; ' if previous else '')+'Время сценария истекло'
                        else: player['scenario_result']='Сценарий отменён: участник отключился или не загрузил сцену'
                        player.setdefault('scenarioQueueBlocked',set()).update(DEFINITIONS)
                        await move(player,None,None)
                continue
            if not session['started']:continue
            check_new_passage(session,players,definition,WORLDS[definition['id']])
            for pid in active:
                player=players[pid];state=player['vehicle'];body=player['vertical']
                finish=definition['finishes'][player['roleId']]
                dx,dz=state.x-finish['x'],state.z-finish['z'];angle=finish['heading']
                stopped=(abs(dx*math.cos(angle)-dz*math.sin(angle))<=.65
                         and abs(dx*math.sin(angle)+dz*math.cos(angle))<=1.5
                         and abs(state.speed)<=.5 and body.grounded
                         and math.cos(state.heading-angle)>.8)
                if definition.get('finishMode')=='pass':
                    forward=dx*math.sin(angle)+dz*math.cos(angle)
                    sideways=dx*math.cos(angle)-dz*math.sin(angle)
                    stopped=0<=forward<=3 and abs(sideways)<=1.5 and body.grounded and math.cos(state.heading-angle)>.8
                if not stopped:session['finish_times'].pop(pid,None);continue
                session['finish_times'].setdefault(pid,now)
                if now-session['finish_times'][pid]<(0 if definition.get('finishMode')=='pass' else 1):continue
                if not finished_route(player,session):
                    player['scenario_result']='Нарушение: маршрут не пройден полностью'
                player['scenario_result']=player.get('scenario_result') or 'Проезд выполнен правильно'
                session['finished'].add(pid)
                # World and scene share coordinates: finished vehicle returns at its actual exit.
                player['return_state']=(state,body)
                player.setdefault('scenarioQueueBlocked',set()).update(DEFINITIONS)
                await move(player,None,None)
            if len(session['finished'])==len(session['players']):self.sessions.pop(scene_id,None)
        for key,definition in DEFINITIONS.items():
            queue=self.waiters[key]
            zone=definition['trigger']
            for player in players.values():
                state=player['vehicle']
                if not (zone['minX']-2 <= state.x <= zone['maxX']+2 and zone['minZ']-2 <= state.z <= zone['maxZ']+2):
                    player.get('scenarioQueueBlocked',set()).discard(key)
            for pid in list(queue):
                if pid not in players or pid not in ready or players[pid]['sceneKind']!='world' or key in players[pid].get('scenarioQueueBlocked',set()) or not waiting(players[pid],definition):queue.pop(pid,None)
            for pid,player in players.items():
                if pid in ready and player['sceneKind']=='world' and key not in player.get('scenarioQueueBlocked',set()) and waiting(player,definition):queue.setdefault(pid,now)
            candidates=sorted((time,pid) for pid,time in queue.items() if now-time>=1)
            required=definition['requiredPlayers']
            if len(candidates)<required:self.pair_since.pop(key,None);continue
            self.pair_since.setdefault(key,now)
            if now-self.pair_since[key]<.5:continue
            self.pair_since.pop(key,None)
            while len(candidates)>=required:
                group,candidates=candidates[:required],candidates[required:]
                self.counter+=1;scene_id=f'scenario:{key}:{self.counter}'
                ids=[pid for _,pid in group]
                secrets.SystemRandom().shuffle(ids)
                self.sessions[scene_id]=dict(id=scene_id,scenarioKey=key,players=ids,finished=set(),finish_times={},deadline=now+30,started=False)
                for role,pid in enumerate(ids):
                    queue.pop(pid,None);players[pid]['scenarioKey']=key
                    players[pid]['scenario_errors']=[]
                    await move(players[pid],scene_id,role)
                for pid in ids:await prepare(players[pid])

    def start(self,scene_id,ready):
        session=self.sessions.get(scene_id)
        if not session or session['started'] or not all(pid in ready for pid in session['players']):return []
        session['started']=True
        session['deadline']=self.now+DEFINITIONS[session['scenarioKey']]['timeLimitSeconds']
        return session['players']
