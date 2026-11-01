"""Actual HTTP/cookie/WebSocket exchange against an isolated in-process app."""
from contextlib import ExitStack
from pathlib import Path
import gc
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
import server.app as game
from server.auth import AuthService
from server.db import Database
from server.scenarios import ScenarioSessions
from server.scenario_registry import DEFINITIONS,WORLDS,body_at
from server.vehicle import VehicleState,Controls


def receive(ws,kind,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        message=ws.receive_json()
        if message['type']==kind:return message
    raise AssertionError(f'Timed out waiting for {kind}')


class SocketTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=(game.database,game.auth,game.scenarios)
        game.database=Database(Path(self.temp.name)/'game.sqlite3');game.auth=AuthService(game.database);game.scenarios=ScenarioSessions()
    def tearDown(self):
        game.database,game.auth,game.scenarios=self.old;gc.collect();self.temp.cleanup()
    def run_scenario(self,key):
        definition=DEFINITIONS[key]
        with TestClient(game.app) as client,ExitStack() as stack:
            peers=[]
            for index in range(definition['requiredPlayers']):
                response=client.post('/api/v2/register',json=dict(username=f'test{index}',password='testpassword',name=f'Test {index}'))
                self.assertEqual(response.status_code,200)
                ws=stack.enter_context(client.websocket_connect('/ws/v2',headers={'cookie':f'game_session={client.cookies.get("game_session")}'}))
                ws.send_json(dict(type='join',v=2));welcome=receive(ws,'welcome');prepare=receive(ws,'scene_prepare')
                ws.send_json(dict(type='scene_ready',sceneId=prepare['sceneId'],epoch=prepare['epoch'],revision=1));receive(ws,'scene_start')
                peers.append((welcome['playerId'],ws))
            async def stage():
                for index,(pid,_) in enumerate(peers):
                    player=game.v2_players[pid];spawn=definition['roles'][index]['spawn']
                    if key=='bridge-junction':
                        x,z,h=[(28,-38.5,-1.5708),(34,-38.5,-1.5708),(40,-38.5,-1.5708),(32,-41.5,1.5708)][index]
                        spawn=dict(x=x,z=z,heading=h)
                    state=VehicleState(**spawn)
                    player.update(vehicle=state,vertical=body_at(game.vehicle_world,spawn),controls=Controls(brake=1))
            client.portal.call(stage)
            assignments=[]
            for pid,ws in peers:
                prepare=receive(ws,'scene_prepare')
                self.assertEqual(prepare['scenarioId'],key)
                self.assertEqual(len(prepare['participants']),definition['requiredPlayers'])
                self.assertEqual(prepare['plan']['mapManifestUrl'],definition['manifestUrl'])
                assigned=next(r for r in definition['roles'] if r['id']==prepare['roleId'])
                self.assertAlmostEqual(prepare['finish']['y'],body_at(WORLDS[key],assigned['finish']).y,places=2)
                self.assertEqual(prepare['vehicleType'],assigned.get('vehicleType','car'))
                assignments.append((pid,ws,prepare))
                ws.send_json(dict(type='scene_ready',sceneId=prepare['sceneId'],epoch=prepare['epoch'],revision=1))
            self.assertEqual(len({p['roleId'] for _,_,p in assignments}),definition['requiredPlayers'])
            starts=[receive(ws,'scene_start') for _,ws,_ in assignments]
            self.assertEqual(len({s['startTick'] for s in starts}),1)
            for _,ws,p in assignments:
                snap=receive(ws,'snapshot');self.assertEqual(len(snap['players']),definition['requiredPlayers']);self.assertEqual(snap['sceneId'],p['sceneId'])
            # A stale input from the prior world epoch must not change scenario controls.
            pid,ws,prepare=assignments[0]
            ws.send_json(dict(type='input',sceneId='world:main',epoch=1,seq=100,throttle=1,steering=0,brake=0))
            receive(ws,'snapshot')
            self.assertEqual(game.v2_players[pid]['seq'],0)
            # A legal fresh input is applied by the live physics loop.
            before=game.v2_players[pid]['vehicle']
            ws.send_json(dict(type='input',sceneId=prepare['sceneId'],epoch=prepare['epoch'],seq=1,throttle=1,steering=0,brake=0))
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                snap=receive(ws,'snapshot')
                own=next(p for p in snap['players'] if p['id']==pid)
                if own['lastInputSeq']==1 and (abs(own['x']-before.x)+abs(own['z']-before.z)>.001):break
            else:self.fail('Authoritative movement was not observed')
            # Finish transition itself: emulate already completed route progress on the test loop.
            async def at_finish():
                player=game.v2_players[pid];role=next(r for r in definition['roles'] if r['id']==player['roleId']);state=VehicleState(**role['finish'])
                player.update(vehicle=state,vertical=body_at(WORLDS[key],role['finish']),controls=Controls(brake=1),input_time=0,scenario_result='Проезд выполнен правильно')
                scene=game.scenarios.sessions[player['sceneId']]
                if True:
                    from server.local_scenario_rules import project
                    *_,total=project(role['route'],state.x,state.z)
                    scene.setdefault('tracks',{})[pid]=dict(progress=total,maxProgress=total,total=total,entered=True,cleared=True)
            client.portal.call(at_finish)
            returned=receive(ws,'scene_prepare')
            self.assertEqual(returned['sceneKind'],'world');self.assertEqual(returned['scenarioResult'],'Проезд выполнен правильно')
            role=next(r for r in definition['roles'] if r['id']==prepare['roleId'])
            for axis in ('x','z','heading'):self.assertAlmostEqual(returned['spawn'][axis],role['finish'][axis])
            self.assertEqual(returned['epoch'],prepare['epoch']+1)
            # Survivor remains in isolated scenario after personal finish.
            other=game.v2_players[assignments[1][0]];self.assertEqual(other['sceneKind'],'scenario')
    def test_bridge_four_clients(self):self.run_scenario('bridge-junction')
    def test_equal_priority_three_clients(self):self.run_scenario('equal-priority')
    def test_roundabout_three_clients(self):self.run_scenario('roundabout')
    def test_first_three_player_scenario(self):self.run_scenario('left-turn')

if __name__=='__main__':unittest.main()

