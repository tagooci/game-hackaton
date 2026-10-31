import json
import math
from pathlib import Path

import pytest
from server.road_surface import RoadSurface
from server.db import Database

NAV = json.loads((Path(__file__).resolve().parents[2] / 'client/public/content/world/navigation.json').read_text())


def test_bridge_height_is_continuous_and_underpass_stays_at_ground():
    road = RoadSurface(NAV['surfaces'])
    previous = 0
    heights = []
    for step in range(-800, 801):
        z = step / 10
        y, pitch = road.sample(0, z, 0, previous)
        expected = max(0, min(5, (65-abs(z))*.1))
        assert y == pytest.approx(expected)
        assert abs(y-previous) <= .011
        if -64 < z < -16:
            assert pitch == pytest.approx(-math.atan(.1))
        heights.append(y)
        previous = y
    assert max(heights) == 5
    for x in range(-80, 81):
        assert road.sample(x, 0, math.pi/2, 0) == pytest.approx((0, 0))
    assert road.sample(0, 0, 0, 5) == pytest.approx((5, 0))


def test_saved_position_keeps_bridge_level_and_world_version(tmp_path):
    db = Database(tmp_path / 'test.sqlite3')
    db.initialize()
    player = db.create_account('driver', 'hash')
    db.save_safe_position(player, 0, 0, 0, 5, 'compact-interchanges-v2')
    db.initialize()
    assert db.safe_context(player) == ('compact-interchanges-v2', 5)
    assert db.safe_position(player) == (0, 0, 0)
