import math
import unittest
from server.scenario_registry import DEFINITIONS,WORLDS,body_at
from server.local_scenario_rules import check_new_passage,conflict_windows,project
from server.scenarios import ScenarioSessions,waiting
from server.vehicle import VehicleState
from server.world_physics import penetration
from test_local_scenarios import player,session
import test_local_scenarios as lifecycle_support


class NewContentTests(unittest.TestCase):
    def test_geometry_and_spawn_support_for_both_new_scenes(self):
        for key in ('left-turn','bridge-junction'):
            d=DEFINITIONS[key];w=WORLDS[key]
            for role in d['roles']:
                points=role['route']
                for i,(x,z) in enumerate(points):
                    a=points[max(0,i-1)];b=points[min(i+1,len(points)-1)]
                    heading=math.atan2(b[0]-a[0],b[1]-a[1]);body=body_at(w,dict(x=x,z=z,heading=heading))
                    self.assertTrue(body.grounded,(key,role['id'],i))
                    self.assertFalse(any(body.y+1.5>q['minY'] and body.y+.05<q['maxY'] and penetration(x,z,heading,q) for q in w.nearby(x,z)),(key,role['id'],i))
    def test_each_intended_priority_has_geometric_conflict(self):
        for key in ('left-turn','bridge-junction'):
            d=DEFINITIONS[key];windows=conflict_windows(d)
            for role,peers in d['yieldsTo'].items():
                for peer in peers:
                    self.assertIn((role,peer),windows)
                    a,b,c,e=windows[role,peer];self.assertGreater(b,a);self.assertGreater(e,c)
        d=DEFINITIONS['bridge-junction'];a=d['roles'][1]['route'];b=d['roles'][2]['route']
        self.assertGreater(min(math.dist(x,y) for x in a for y in b),2.2,'Opposing straight routes must remain independent lanes')
    def test_world_return_height_matches_ramp_scene(self):
        from server.app import vehicle_world
        for key in ('left-turn','bridge-junction'):
            for role in DEFINITIONS[key]['roles']:
                actual=body_at(vehicle_world,role['finish']);scene=body_at(WORLDS[key],role['finish'])
                self.assertTrue(actual.grounded);self.assertAlmostEqual(actual.y,scene.y,places=3)
        self.assertGreater(body_at(WORLDS['bridge-junction'],DEFINITIONS['bridge-junction']['roles'][0]['spawn']).y,1)
    def test_all_routes_can_be_completed_without_false_violations(self):
        for key in ('left-turn','bridge-junction'):
            d=DEFINITIONS[key]
            for role in d['roles']:
                p=player('p',key,role);p['sceneId']='scenario:test';s=session(key,{'p':p});pts=role['route']
                for i,(x,z) in enumerate(pts):
                    a=pts[max(i-1,0)];b=pts[min(i+1,len(pts)-1)];p['vehicle']=VehicleState(x,z,math.atan2(b[0]-a[0],b[1]-a[1]),2)
                    p['vertical']=body_at(WORLDS[key],dict(x=x,z=z,heading=p['vehicle'].heading))
                    check_new_passage(s,{'p':p},d,WORLDS[key])
                self.assertIsNone(p['scenario_result'],(key,role['id'],p.get('scenario_errors')))
    def test_three_and_four_roles_have_no_overlapping_starts(self):
        for key,count in [('left-turn',3),('bridge-junction',4)]:
            d=DEFINITIONS[key];self.assertEqual(len(d['roles']),count);self.assertEqual(d['requiredPlayers'],count)
            for i,a in enumerate(d['roles']):
                for b in d['roles'][i+1:]:self.assertGreater(math.hypot(a['spawn']['x']-b['spawn']['x'],a['spawn']['z']-b['spawn']['z']),4)
    def test_new_scene_hashes_and_cache_budget(self):
        import gzip,hashlib,json
        from server.scenario_registry import ROOT
        for folder in ('left-turn-v2','bridge-junction'):
            manifest=json.loads((ROOT/folder/'manifest.json').read_text())
            for resource in manifest['resources']:
                data=(ROOT.parents[1]/resource['url'].lstrip('/')).read_bytes()
                self.assertEqual(len(data),resource['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(),resource['sha256'])
                self.assertTrue(gzip.decompress(data))
            self.assertLess(sum(r['bytes'] for r in manifest['resources'])+sum(r['bytes'] for r in manifest['residentResources'])+len(json.dumps(manifest).encode()),manifest['cacheBudgetBytes'])

    def test_legacy_content_is_still_available(self):
        import json
        from server.scenario_registry import ROOT
        old=json.loads((ROOT/'left-turn/scenario.json').read_text())
        self.assertEqual(len(old['spawns']),2)
        self.assertNotEqual(DEFINITIONS['left-turn']['manifestUrl'],old['manifestUrl'])


class PriorityTests(unittest.TestCase):
    def setup_pair(self,key,role_id,peer_id,threat):
        d=DEFINITIONS[key];own_role=next(r for r in d['roles'] if r['id']==role_id);peer_role=next(r for r in d['roles'] if r['id']==peer_id)
        a=player('a',key,own_role);b=player('b',key,peer_role);ps={'a':a,'b':b};s=session(key,ps)
        start,end,peer_start,peer_end=conflict_windows(d)[role_id,peer_id]
        def at(route,distance):
            along=0
            for p,q in zip(route,route[1:]):
                length=math.dist(p,q)
                if length and along+length>=distance:
                    t=(distance-along)/length;return VehicleState(p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1]),math.atan2(q[0]-p[0],q[1]-p[1]),2)
                along+=length
            return VehicleState(**peer_role['finish'])
        a['vehicle']=at(own_role['route'],start+.2)
        if threat:b['vehicle']=at(peer_role['route'],peer_start+.2)
        for p in ps.values():
            p['sceneId']='scenario:test';p['vertical']=body_at(WORLDS[key],dict(x=p['vehicle'].x,z=p['vehicle'].z,heading=p['vehicle'].heading))
            _,progress,_,total=project(next(r for r in d['roles'] if r['id']==p['roleId'])['route'],p['vehicle'].x,p['vehicle'].z)
            s['tracks'][p['id']]=dict(progress=progress,maxProgress=progress,total=total,entered=False)
        check_new_passage(s,ps,d,WORLDS[key]);return a
    def test_bridge_ramp_yields_to_all_three_priority_roles(self):
        for peer in ('east-straight','west-straight','east-left'):
            p=self.setup_pair('bridge-junction','ramp-left',peer,True)
            self.assertIn('преимуществом',p['scenario_result'])
    def test_bridge_left_turn_yields_to_oncoming(self):
        self.assertIn('преимуществом',self.setup_pair('bridge-junction','east-left','west-straight',True)['scenario_result'])
    def test_first_left_turn_checks_following_car_as_well_as_truck(self):
        for peer in ('truck-right','north-follow'):
            self.assertIn('преимуществом',self.setup_pair('left-turn','south-left',peer,True)['scenario_result'])
    def test_stationary_distant_peer_does_not_force_fixed_order(self):
        p=self.setup_pair('bridge-junction','ramp-left','east-left',False)
        self.assertIsNone(p['scenario_result'])


class BridgeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = lifecycle_support.LifecycleTests.asyncSetUp
    tick = lifecycle_support.LifecycleTests.tick
    async def test_fourth_player_is_required_for_bridge(self):
        d=DEFINITIONS['bridge-junction']
        for i in range(3):
            pid=str(i);p=player(pid,'bridge-junction',d['roles'][i]);p['vehicle']=VehicleState(28+i*6,-38.5,-math.pi/2);p['vertical']=body_at(WORLDS['bridge-junction'],dict(x=p['vehicle'].x,z=p['vehicle'].z,heading=p['vehicle'].heading));self.players[pid]=p;self.ready.add(pid)
        for t in (0,1.1,2):await self.tick(t)
        self.assertFalse(self.manager.sessions)
    async def test_bridge_finish_returns_immediately_while_moving(self):
        key='bridge-junction';d=DEFINITIONS[key];ps={}
        for i,r in enumerate(d['roles']):
            p=player(str(i),key,r);p['sceneId']='scenario:test';p['sceneKind']='scenario';p['return_state']=(p['vehicle'],p['vertical']);ps[p['id']]=p
        self.players=ps;s=session(key,ps);s.update(started=True,deadline=100,finish_times={})
        self.manager.sessions[s['id']]=s
        p=ps['2'];r=d['roles'][2];p['vehicle']=VehicleState(**r['finish'],speed=3);p['vertical']=body_at(WORLDS[key],r['finish'])
        _,progress,_,total=project(r['route'],p['vehicle'].x,p['vehicle'].z);s['tracks']['2']=dict(progress=progress,maxProgress=total,total=total,entered=True)
        await self.tick(1)
        self.assertEqual(p['sceneId'],'world:main');self.assertEqual(len(self.returns),1)

if __name__=='__main__':unittest.main()
