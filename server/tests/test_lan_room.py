import math
import unittest

from server.scenarios.intersection import load_definition
from server.scenarios.lan_room import LanRoom, step


class LanRoomTests(unittest.TestCase):
    def running(self, count=2):
        room = LanRoom()
        ids = [room.connect(f'Driver {i}') for i in range(count)]
        for pid in ids:
            room.join_queue(pid, 0)
        room.advance(10)
        for pid in ids:
            room.ready(pid, room.session.scene_id, 11)
        room.advance(14)
        return room, ids

    def command(self, room, seq=1, throttle=1):
        return {'sceneId': room.session.scene_id, 'seq': seq,
                'throttle': throttle, 'steering': 0, 'brake': 0}

    def test_only_three_connections(self):
        room, ids = self.running(3)
        self.assertIsNone(room.connect('Fourth'))
        self.assertEqual(len(room.snapshot(ids[0], 14)['players']), 3)

    def test_controls_require_current_scene_sequence_and_finite_values(self):
        room, ids = self.running()
        pid = ids[0]
        self.assertTrue(room.input(pid, self.command(room), 14))
        self.assertFalse(room.input(pid, self.command(room), 14))
        self.assertFalse(room.input(pid, {**self.command(room, 2), 'sceneId': 'old'}, 14))
        self.assertFalse(room.input(pid, self.command(room, 2, math.nan), 14))
        self.assertFalse(room.input(pid, self.command(room, 2, True), 14))

    def test_packets_do_not_advance_simulation(self):
        room, ids = self.running()
        before = room.drivers[ids[0]].pose
        for seq in range(1, 100):
            room.input(ids[0], self.command(room, seq), 14)
        self.assertEqual(before, room.drivers[ids[0]].pose)
        room.advance(14.03)
        self.assertGreater(room.drivers[ids[0]].pose.speed, 0)

    def test_input_lease_brakes_after_disconnect_or_focus_loss(self):
        room, ids = self.running()
        pid = ids[0]
        room.input(pid, self.command(room), 14)
        room.advance(14.03)
        room.advance(15)
        self.assertEqual(room.drivers[pid].pose.speed, 0)

    def test_disconnect_cancels_and_returns_remaining_player(self):
        room, ids = self.running()
        origin = room.session.participants[ids[1]].returns.origin
        room.disconnect(ids[0], 15)
        room.advance(15)
        self.assertEqual(room.snapshot(ids[1], 15)['phase'], 'cancelled')
        room.advance(20)
        self.assertIsNone(room.session)
        self.assertEqual(room.drivers[ids[1]].pose, origin)
        self.assertEqual(room.snapshot(ids[1], 20)['phase'], 'lobby')

    def test_spectator_arriving_after_roster_lock_is_not_in_session(self):
        room, ids = self.running()
        spectator = room.connect('Late arrival')
        self.assertEqual(room.snapshot(spectator, 14)['phase'], 'lobby')
        self.assertEqual(len(room.snapshot(spectator, 14)['players']), 1)
        self.assertEqual(len(room.snapshot(ids[0], 14)['players']), 2)
        self.assertFalse(room.join_queue(spectator, 14))

    def test_countdown_does_not_apply_controls(self):
        room = LanRoom()
        ids = [room.connect('A'), room.connect('B')]
        for pid in ids:
            room.join_queue(pid, 0)
        room.advance(10)
        self.assertFalse(room.input(ids[0], self.command(room), 10))

    def test_tram_keeps_track_even_when_steering(self):
        from server.scenarios.intersection import Pose
        role = load_definition()['roles'][2]
        pose = Pose(**role['spawn'])
        for _ in range(90):
            pose = step(pose, (1, 1, 0), role, 1 / 30)
        self.assertAlmostEqual(pose.x, role['spawn']['x'])
        self.assertAlmostEqual(pose.heading, role['spawn']['heading'])
        self.assertLess(pose.z, role['spawn']['z'])


if __name__ == '__main__':
    unittest.main()
