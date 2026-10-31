"""Dependency-free domain checks: python -m unittest server.tests.test_intersection."""
import math
import random
import tempfile
from pathlib import Path
import unittest

from server.scenarios.intersection import (
    IntersectionSession, Pose, ReturnPoints, ScenarioQueue, corners, overlapping,
)
from server.scenarios.results import ResultStore


def returns():
    return ReturnPoints(Pose(0, -50, 0), {
        'north': Pose(3.5, 40, 0), 'east': Pose(40, -3.5, math.pi / 2),
        'south': Pose(-3.5, -40, -math.pi), 'west': Pose(-40, 3.5, -math.pi / 2),
    })


class ScenarioTests(unittest.TestCase):
    def session(self, count=2):
        session = IntersectionSession({f'p{i}': returns() for i in range(count)}, 0, rng=random.Random(3))
        return session

    def ready(self, session):
        for pid in session.participants:
            session.mark_ready(pid, session.scene_id, 1)
        session.advance(4, {})

    def test_queue_waits_ten_seconds_and_supports_third(self):
        queue = ScenarioQueue()
        queue.join('a', returns(), 0)
        self.assertIsNone(queue.advance(100))
        queue.join('b', returns(), 100)
        queue.join('c', returns(), 105)
        self.assertFalse(queue.join('d', returns(), 106))
        self.assertIsNone(queue.advance(109.9))
        session = queue.advance(110, random.Random(3))
        self.assertEqual({p.role['vehicleType'] for p in session.participants.values()}, {'car', 'truck', 'tram'})
        self.assertEqual(queue.waiting, {})

    def test_leave_resets_queue_deadline(self):
        queue = ScenarioQueue()
        queue.join('a', returns(), 0)
        queue.join('b', returns(), 1)
        queue.leave('b')
        self.assertIsNone(queue.deadline)
        self.assertIsNone(queue.advance(100))

    def test_all_must_load_and_stale_ready_does_nothing(self):
        s = self.session()
        self.assertFalse(s.mark_ready('p0', 'old-scene', 1))
        s.mark_ready('p0', s.scene_id, 1)
        s.advance(3, {})
        self.assertEqual(s.phase, 'loading')
        s.mark_ready('p1', s.scene_id, 3)
        s.advance(5.9, {})
        self.assertEqual(s.phase, 'countdown')
        s.advance(6, {})
        self.assertEqual(s.phase, 'running')

    def test_loading_timeout_cancelled_without_penalty(self):
        s = self.session()
        result = s.advance(30, {})
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['violations'], [])

    def test_readiness_after_loading_deadline_cannot_start_session(self):
        s = self.session()
        self.assertFalse(s.mark_ready('p0', s.scene_id, 31))
        self.assertEqual(s.result['reason'], 'loading_timeout')

    def test_disconnect_is_idempotent_and_returns_to_origin(self):
        s = self.session()
        s.disconnect('p0', 1)
        first = s.result
        s.disconnect('p1', 2)
        self.assertIs(s.result, first)
        self.assertEqual(s.return_pose('p1'), returns().origin)

    def test_timeout(self):
        s = self.session()
        self.ready(s)
        self.assertEqual(s.advance(94, {})['status'], 'timeout')

    def test_collision(self):
        s = self.session()
        self.ready(s)
        result = s.advance(5, {pid: Pose(0, 0, 0) for pid in s.participants})
        self.assertEqual(result['reason'], 'collision')

    def test_success_in_priority_order_and_exit_return(self):
        s = self.session()
        self.ready(s)
        truck = next(p for p in s.participants.values() if p.role['vehicleType'] == 'truck')
        car = next(p for p in s.participants.values() if p.role['vehicleType'] == 'car')
        s.advance(5, {truck.player_id: Pose(5, 3.5, -math.pi / 2)})
        self.assertIsNone(s.result)
        s.advance(6, {truck.player_id: Pose(-36, 3.5, -math.pi / 2)})
        self.assertEqual(truck.exit, 'west')
        s.advance(7, {car.player_id: Pose(3.5, -5, 0)})
        result = s.advance(8, {car.player_id: Pose(3.5, 34, 0)})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(s.return_pose(car.player_id), returns().exits['north'])

    def test_priority_violation_does_not_end_run(self):
        s = self.session()
        self.ready(s)
        car = next(p for p in s.participants.values() if p.role['vehicleType'] == 'car')
        s.advance(5, {car.player_id: Pose(3.5, -5, 0)})
        s.advance(6, {car.player_id: Pose(3.5, 34, 0)})
        self.assertEqual(s.violations[0]['ruleId'], 'yield_right')
        self.assertEqual(s.phase, 'running')
        self.assertIsNone(s.result)

    def test_three_players_tram_then_truck_then_car(self):
        s = self.session(3)
        self.ready(s)
        by_type = {p.role['vehicleType']: p for p in s.participants.values()}
        tram, truck, car = (by_type[key] for key in ('tram', 'truck', 'car'))
        s.advance(5, {tram.player_id: Pose(-1.5, 0, -math.pi)})
        s.advance(6, {tram.player_id: Pose(-1.5, -38, -math.pi)})
        self.assertEqual(tram.exit, 'south')
        s.advance(7, {truck.player_id: Pose(5, 3.5, -math.pi / 2)})
        s.advance(8, {truck.player_id: Pose(-36, 3.5, -math.pi / 2)})
        s.advance(9, {car.player_id: Pose(3.5, -5, 0)})
        # The actual west exit is a left turn for a car arriving from south.
        result = s.advance(10, {car.player_id: Pose(-34, 3.5, -math.pi / 2)})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(s.return_pose(car.player_id), returns().exits['west'])

    def test_grass_and_wrong_heading_are_not_finish_zones(self):
        s = self.session()
        p = next(iter(s.participants.values()))
        p.pose = Pose(20, 40, 0)
        self.assertIsNone(s._exit(p))
        p.pose = Pose(3.5, 40, math.pi)
        self.assertIsNone(s._exit(p))

    def test_oriented_rectangles(self):
        self.assertTrue(overlapping(corners(Pose(0, 0, .7), 8, 2), corners(Pose(1, 0, 0), 4, 2)))
        self.assertFalse(overlapping(corners(Pose(0, 0, 0), 4, 2), corners(Pose(10, 0, 0), 4, 2)))

    def test_sqlite_result_survives_reopen_and_is_not_duplicated(self):
        s = self.session()
        s.disconnect('p0', 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'results.sqlite3'
            store = ResultStore(path)
            self.assertTrue(store.save(s.result))
            self.assertFalse(store.save(s.result))
            store.close()
            store = ResultStore(path)
            self.assertEqual(store.get(s.result['resultId']), s.result)
            store.close()


if __name__ == '__main__':
    unittest.main()
