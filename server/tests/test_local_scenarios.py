import asyncio
import gzip
import hashlib
import json
import math
import unittest
from pathlib import Path

from server.scenario_registry import DEFINITIONS, WORLDS
from server.scenarios import ScenarioSessions, waiting
from server.local_scenario_rules import check_new_passage, project
from server.vehicle import VehicleState, Controls
from server.world_physics import penetration

ROOT=Path(__file__).resolve().parents[2]/'client/public'


def player(pid,key,role=None):
    definition=DEFINITIONS[key];role=role or definition['roles'][0]
    state=VehicleState(**role['spawn'])
    return dict(id=pid,vehicle=state,vertical=WORLDS[key].restore(state.x,state.z,state.heading,.1),sceneId='world:main',sceneKind='world',roleId=role['id'],scenarioKey=key,controls=Controls(),scenario_result=None)


def session(key,players):return dict(id='scenario:test',players=list(players),finished=set(),scenarioKey=key,tracks={})


class ContentTests(unittest.TestCase):
    def test_all_reference_routes_are_drivable(self):
        for key in ('equal-priority','roundabout'):
            w=WORLDS[key]
            for role in DEFINITIONS[key]['roles']:
                pts=role['route']
                for i,(x,z) in enumerate(pts):
                    a=pts[max(0,i-1)];b=pts[min(len(pts)-1,i+1)]
                    h=math.atan2(b[0]-a[0],b[1]-a[1]);body=w.restore(x,z,h,.1)
                    self.assertTrue(body.grounded,(key,role['id'],i))
                    hits=[q for q in w.nearby(x,z) if body.y+1.5>q['minY'] and body.y+.05<q['maxY'] and penetration(x,z,h,q)]
                    self.assertFalse(hits,(key,role['id'],i))
    def test_manifest_resources_and_hashes(self):
        for key in ('equal-priority','roundabout'):
            manifest=json.loads((ROOT/f'content/scenarios/{key}/manifest.json').read_text())
            self.assertEqual(len({r['id'] for r in manifest['resources']}),len(manifest['resources']))
            for r in manifest['resources']:
                data=(ROOT/r['url'].lstrip('/')).read_bytes()
                self.assertEqual(len(data),r['bytes']);self.assertEqual(hashlib.sha256(data).hexdigest(),r['sha256'])
                if r['encoding']=='gzip':self.assertTrue(gzip.decompress(data))
            self.assertLess(sum(r['bytes'] for r in manifest['resources'])+sum(r['bytes'] for r in manifest['residentResources'])+len(json.dumps(manifest).encode()),manifest['cacheBudgetBytes'])
    def test_returns_share_world_ground(self):
        from server.app import vehicle_world
        for key in ('equal-priority','roundabout'):
            for role in DEFINITIONS[key]['roles']:
                pose=role['finish'];body=vehicle_world.restore(**pose,y=.1)
                self.assertTrue(body.grounded)
                self.assertAlmostEqual(body.y,.1,places=2)
    def test_bridge_not_queue(self):
        p=player('a','roundabout');p['vertical']=type(p['vertical'])(y=5.1)
        self.assertFalse(waiting(p,DEFINITIONS['roundabout']))


class RuleTests(unittest.TestCase):
    def test_correct_routes_without_peers_have_no_errors(self):
        for key in ('equal-priority','roundabout'):
            for role in DEFINITIONS[key]['roles']:
                p=player('p',key,role);p['sceneId']='scenario:test';s=session(key,{'p':p});pts=role['route']
                for i,(x,z) in enumerate(pts):
                    a=pts[max(i-1,0)];b=pts[min(i+1,len(pts)-1)]
                    p['vehicle']=VehicleState(x,z,math.atan2(b[0]-a[0],b[1]-a[1]),speed=2)
                    check_new_passage(s,{'p':p},DEFINITIONS[key],WORLDS[key])
                self.assertIsNone(p['scenario_result'],(key,role['id'],p.get('scenario_errors')))
    def test_equal_yield_to_right(self):
        key='equal-priority';d=DEFINITIONS[key]
        a=player('a',key,d['roles'][0]);b=player('b',key,d['roles'][1]);c=player('c',key,d['roles'][2])
        ps={'a':a,'b':b,'c':c}
        for p in ps.values():p['sceneId']='scenario:test'
        a['vehicle']=VehicleState(31.5,-14,0,2);b['vehicle']=VehicleState(34,-8.5,-math.pi/2,2)
        check_new_passage(session(key,ps),ps,d,WORLDS[key])
        self.assertIn('преимуществом',a['scenario_result'])
    def test_safe_gap_does_not_require_fixed_order(self):
        key='equal-priority';d=DEFINITIONS[key];a=player('a',key,d['roles'][0]);b=player('b',key,d['roles'][1])
        for p in (a,b):p['sceneId']='scenario:test'
        a['vehicle']=VehicleState(31.5,-14,0,2);b['vehicle']=VehicleState(43,-8.5,-math.pi/2,0)
        current=session(key,{'a':a,'b':b})
        current['tracks']['a']=dict(progress=9,maxProgress=9,entered=False)
        check_new_passage(current,{'a':a,'b':b},d,WORLDS[key])
        self.assertIsNone(a['scenario_result'])
    def test_ring_merge_and_wrong_way(self):
        key='roundabout';d=DEFINITIONS[key];a=player('a',key,d['roles'][0]);c=player('c',key,d['roles'][2]);ps={'a':a,'c':c}
        for p in ps.values():p['sceneId']='scenario:test'
        a['vehicle']=VehicleState(1.5,-51,0,2)
        c['vehicle']=VehicleState(-2,-48,math.pi/2,3)
        s=session(key,ps);s['tracks']={'c':dict(progress=0,maxProgress=0,entered=True)}
        check_new_passage(s,ps,d,WORLDS[key]);self.assertIn('въезде',a['scenario_result'])
        c['vehicle']=VehicleState(8,-40,math.pi,2)
        check_new_passage(s,ps,d,WORLDS[key]);self.assertIn('обратную',c['scenario_result'])
    def test_collision_is_recorded_for_both(self):
        key='equal-priority';d=DEFINITIONS[key];a=player('a',key);b=player('b',key,d['roles'][1]);ps={'a':a,'b':b}
        for p in ps.values():p['sceneId']='scenario:test';p['vehicle']=VehicleState(30,-10)
        check_new_passage(session(key,ps),ps,d,WORLDS[key])
        for p in ps.values():self.assertIn('столкновение',p['scenario_result'])
    def test_finish_shortcut_is_not_accepted(self):
        from server.local_scenario_rules import finished_route
        key='roundabout';p=player('p',key);p['sceneId']='scenario:test';p['vehicle']=VehicleState(**DEFINITIONS[key]['roles'][0]['finish']);s=session(key,{'p':p})
        check_new_passage(s,{'p':p},DEFINITIONS[key],WORLDS[key]);self.assertFalse(finished_route(p,s))


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager=ScenarioSessions();self.players={};self.ready=set();self.returns=[]
        async def move(p,scene_id,role):
            self.ready.discard(p['id'])
            if scene_id:
                p['return_state']=(p['vehicle'],p['vertical']);d=DEFINITIONS[p['scenarioKey']];p['roleId']=d['roleIds'][role];p['vehicle']=VehicleState(**d['spawns'][role]);p['vertical']=WORLDS[d['id']].restore(p['vehicle'].x,p['vehicle'].z,p['vehicle'].heading,.1)
            else:
                self.returns.append((p['id'],p.get('scenario_result'),p['return_state'][0]));p['vehicle'],p['vertical']=p.pop('return_state')
            p['sceneId']=scene_id or 'world:main';p['sceneKind']='scenario' if scene_id else 'world'
        async def prepare(p):pass
        self.move=move;self.prepare=prepare
    async def tick(self,t):await self.manager.update(self.players,self.ready,t,self.move,self.prepare)
    def add(self,key,count):
        for i in range(count):
            pid=f'{key}-{i}';self.players[pid]=player(pid,key,DEFINITIONS[key]['roles'][i]);self.ready.add(pid)
    async def launch(self,key):
        self.add(key,3);await self.tick(0);await self.tick(1.1);await self.tick(1.7)
        return next(s for s in self.manager.sessions.values() if s['scenarioKey']==key)
    async def test_completed_players_are_not_immediately_queued_again(self):
        self.add('equal-priority',3)
        for p in self.players.values():p['scenarioQueueBlocked']={'equal-priority'}
        for t in (0,2,3):await self.tick(t)
        self.assertFalse(self.manager.sessions)
        self.assertFalse(self.manager.waiters['equal-priority'])
        p=next(iter(self.players.values()));p['vehicle']=VehicleState(60,40)
        await self.tick(4)
        self.assertNotIn('equal-priority',p['scenarioQueueBlocked'])

    async def test_two_players_do_not_launch_three_player_scenario(self):
        self.add('equal-priority',2);await self.tick(0);await self.tick(2);await self.tick(3);self.assertFalse(self.manager.sessions)
    async def test_three_players_roles_and_ready_gate(self):
        s=await self.launch('equal-priority');ids=s['players'];self.assertEqual(len({self.players[p]['roleId'] for p in ids}),3)
        self.assertEqual(self.manager.start(s['id'],set(ids[:2])),[])
        self.assertEqual(self.manager.start(s['id'],set(ids)),ids)
        self.assertEqual(self.manager.start(s['id'],set(ids)),[])
    async def test_independent_queues(self):
        self.add('equal-priority',3);self.add('roundabout',3)
        for t in (0,1.1,1.7):await self.tick(t)
        self.assertEqual(len(self.manager.sessions),2)
    async def test_disconnect_returns_remaining_players(self):
        s=await self.launch('roundabout');self.players.pop(s['players'][0]);await self.tick(2)
        self.assertFalse(self.manager.sessions);self.assertEqual(len(self.returns),2)
        self.assertTrue(all('отменён' in result for _,result,_ in self.returns))
    async def test_loading_and_running_timeouts(self):
        s=await self.launch('equal-priority');await self.tick(33);self.assertFalse(self.manager.sessions)
        self.players={};self.ready=set();s=await self.launch('roundabout');self.manager.start(s['id'],set(s['players']));await self.tick(93)
        self.assertFalse(self.manager.sessions);self.assertTrue(any('истекло' in result for _,result,_ in self.returns))
    async def test_personal_finish_returns_to_exact_exit(self):
        s=await self.launch('equal-priority');self.manager.start(s['id'],set(s['players']));pid=s['players'][0];p=self.players[pid];d=DEFINITIONS['equal-priority'];r=next(r for r in d['roles'] if r['id']==p['roleId'])
        # Sample ordered path in isolation to establish genuine route progress.
        others={key:self.players.pop(key) for key in s['players'] if key!=pid}
        points=r['route']
        for i,(x,z) in enumerate(points):
            a=points[max(0,i-1)];b=points[min(len(points)-1,i+1)];p['vehicle']=VehicleState(x,z,math.atan2(b[0]-a[0],b[1]-a[1]),2)
            check_new_passage(s,self.players,d,WORLDS['equal-priority'])
        self.players.update(others);p['vehicle']=VehicleState(**r['finish'])
        await self.tick(3);await self.tick(4.1)
        self.assertEqual(p['sceneId'],'world:main');self.assertEqual(len(self.returns),1)
        self.assertAlmostEqual(self.returns[0][2].x,r['finish']['x']);self.assertEqual(self.returns[0][1],'Проезд выполнен правильно')

if __name__=='__main__':unittest.main()
