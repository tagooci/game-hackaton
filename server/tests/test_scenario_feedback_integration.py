"""Regression checks for merged scenarios using the existing results/XP pipeline."""
import unittest
from unittest.mock import patch
from server.agent import parse_result
from server.scenarios import ScenarioSessions
from server.scenario_registry import DEFINITIONS
from server.passage_results import PassageResults
from test_local_scenarios import player
import server.app as game


class FeedbackIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_scene_reports_violations_and_awards_existing_xp(self):
        for key, definition in DEFINITIONS.items():
            p = player('p', key)
            reports = []
            manager = ScenarioSessions(reports.append)
            results = PassageResults('scenario:test', [p], definition, 0)
            session = dict(players=['p'], finished=set(), results=results)
            p['scenario_errors'] = ['не уступили автомобилю с преимуществом', 'маршрут не пройден полностью']
            manager.record_violations(session, {'p': p}, 1)
            manager.record_violations(session, {'p': p}, 2)
            manager.emit_result(session, 'p', 'completed', 3)
            manager.emit_result(session, 'p', 'completed', 4)
            self.assertEqual(len(reports), 1)
            parsed = parse_result(reports[0])
            self.assertEqual(len(parsed.violations), 2)
            self.assertEqual({v.category.value for v in parsed.violations}, {'rightOfWay', 'trafficSigns'})
            with patch.object(game, 'database') as database, patch.dict(game.v2_connections, {}, clear=True):
                game.submit_agent_result(reports[0])
                args = database.save_scenario_result.call_args.args
                self.assertEqual(args[6], 230 if key == 'bridge-junction' else 130)

    async def test_timeout_and_disconnect_emit_valid_reports_once(self):
        for status in ('timeout', 'cancelled'):
            p = player('p', 'equal-priority')
            p.update(sceneId='scenario:test', sceneKind='scenario')
            peer = player('peer', 'equal-priority', DEFINITIONS['equal-priority']['roles'][1])
            reports = []
            manager = ScenarioSessions(reports.append)
            results = PassageResults('scenario:test', [p, peer], DEFINITIONS['equal-priority'], 0)
            manager.sessions['scenario:test'] = dict(id='scenario:test', scenarioKey='equal-priority',
                players=['p', 'peer'], finished=set(), started=True, deadline=1 if status == 'timeout' else 100, results=results)
            players = {'p': p, 'peer': peer} if status == 'timeout' else {'p': p}
            async def move(player, scene, role):
                player['sceneKind'] = 'world'
                player['sceneId'] = 'world:main'
            async def prepare(player):
                pass
            await manager.update(players, set(), 2, move, prepare)
            self.assertFalse(manager.sessions)
            self.assertEqual(len(reports), 2)
            self.assertTrue(all(parse_result(r).status.value == status for r in reports))
