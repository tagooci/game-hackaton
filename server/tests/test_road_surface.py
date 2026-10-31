import json
import math
from pathlib import Path
import pytest
from server.road_surface import RoadSurface
from server.db import Database

NAV=json.loads((Path(__file__).resolve().parents[2]/'client/public/content/world/navigation.json').read_text())


def test_imported_surface_matches_every_road_port_height():
    surface=RoadSurface(NAV['surfaces'])
    for road in NAV['sourceRoads']:
        for port in road['ports']:
            bx,by,height=port['position']
            dx,dz=port['direction']
            # Полметра внутрь модуля: точно по центру проезжей части.
            x,z=-bx+dx*.5,-by+dz*.5
            y,_=surface.sample(x,z,math.atan2(-dx,-dz),height)
            assert abs(y-height)<.3, (road['object'],port,y)


def test_triangle_surface_slope_and_overlapping_levels():
    lower={'triangle':[[0,0,0],[10,0,0],[0,0,10]]}
    ramp={'triangle':[[0,5,0],[10,6,0],[0,5,10]]}
    surface=RoadSurface([lower,ramp])
    assert surface.sample(2,2,0,0)==pytest.approx((0,0))
    assert surface.sample(2,2,math.pi/2,5)==pytest.approx((5.2,-math.atan(.1)))
    assert surface.sample(100,100,0)==(0,0)


def test_saved_position_keeps_bridge_level_and_world_version(tmp_path):
    db=Database(tmp_path/'test.sqlite3');db.initialize()
    player=db.create_account('driver','hash')
    db.save_safe_position(player,0,0,0,5,'imported-map')
    db.initialize()
    assert db.safe_context(player)==('imported-map',5)
    assert db.safe_position(player)==(0,0,0)
