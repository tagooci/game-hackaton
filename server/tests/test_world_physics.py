import math
from dataclasses import replace

import pytest

from server.vehicle import VehicleState,VehicleConfig,Controls,step_vehicle
from server.world_physics import VehicleWorld,VerticalState,GRAVITY,CAR_LENGTH,penetration


def floor(y,x0=-100,x1=100,z0=-100,z1=100):
    return [{'triangle':[[x0,y,z0],[x1,y,z0],[x0,y,z1]]},
            {'triangle':[[x1,y,z1],[x0,y,z1],[x1,y,z0]]}]


def box(x=0,z=0,heading=0,width=1,length=1,bottom=0,top=4):
    return dict(x=x,z=z,heading=heading,halfWidth=width/2,halfLength=length/2,minY=bottom,maxY=top)


def drive(world,state,body,seconds,controls=Controls(throttle=1),others=()):
    history=[]
    for _ in range(round(seconds*30)):
        proposed=step_vehicle(state,controls,VehicleConfig(),1/30)
        state,body=world.step(state,proposed,body,1/30,others)
        history.append((state,body))
    return state,body,history


def test_underpass_never_attaches_to_upper_bridge_and_upper_car_stays_on_top():
    world=VehicleWorld([*floor(0),*floor(5)],ceilings=floor(4.7))
    state,body,_=drive(world,VehicleState(z=-10),VerticalState(0),4)
    assert state.z>10
    assert body.y==0
    assert body.grounded
    _,upper,_=drive(world,VehicleState(z=-10),VerticalState(5),4)
    assert upper.y==5
    assert world.restore(0,0,0,2).y==2
    assert not world.restore(0,0,0,2).grounded


def test_fall_is_ballistic_and_lands_on_highest_crossed_surface():
    world=VehicleWorld([*floor(0),*floor(3)])
    state=VehicleState(speed=3)
    body=VerticalState(7,grounded=False)
    _,_,history=drive(world,state,body,.3)
    assert [b.y for _,b in history]==pytest.approx([7-GRAVITY*((i+1)/30)**2/2 for i in range(9)])
    state,body,history=drive(world,state,body,2)
    assert body.y==3
    assert body.velocity==0 and body.grounded
    assert all(b.y>=3 for _,b in history)


def test_leaving_bridge_keeps_momentum_and_does_not_snap_to_ground():
    world=VehicleWorld([*floor(0),*floor(5,z0=-10,z1=0)])
    state,body,history=drive(world,VehicleState(z=-3,speed=6),VerticalState(5),2)
    airborne=[(s,b) for s,b in history if not b.grounded]
    assert airborne
    assert airborne[0][1].y>4.9
    assert any(1<b.y<4 for _,b in airborne)
    assert state.z>5 and body.y==0


def test_fast_frontal_collision_cannot_tunnel_through_thin_box():
    wall=box(z=0,width=20,length=.05)
    world=VehicleWorld(floor(0),[wall])
    state,body,_=drive(world,VehicleState(z=-5,speed=22),VerticalState(0),1)
    assert state.z<=-2.22
    assert abs(state.speed)<.01
    assert penetration(state.x,state.z,state.heading,wall) is None


def test_sliding_against_rotated_box_keeps_tangential_motion():
    wall=box(heading=math.pi/4,width=.1,length=30)
    world=VehicleWorld(floor(0),[wall])
    state,body,_=drive(world,VehicleState(x=4,z=-2,speed=10),VerticalState(0),1)
    assert state.z>-2 and state.x>4
    assert penetration(state.x,state.z,state.heading,wall) is None


def test_height_gate_allows_driving_below_deck_boxes_but_stops_at_support():
    deck=box(width=20,length=10,bottom=4.6,top=5)
    world=VehicleWorld(floor(0),[deck])
    state,_,_=drive(world,VehicleState(z=-10),VerticalState(0),4)
    assert state.z>10
    world=VehicleWorld(floor(0),[box(z=0,width=1,length=1,top=5)])
    state,_,_=drive(world,VehicleState(z=-10),VerticalState(0),4)
    assert state.z<-2.6


def test_low_ceiling_blocks_car_instead_of_lifting_it_to_the_roof():
    world=VehicleWorld(floor(0),ceilings=floor(1.3,z0=0,z1=10))
    state,body,_=drive(world,VehicleState(z=-10),VerticalState(0),4)
    assert state.z<-2
    assert body.y==0


def test_cars_collide_only_when_their_heights_overlap():
    world=VehicleWorld(floor(0))
    other=world.car_box(VehicleState(),VerticalState(0))
    state,_,_=drive(world,VehicleState(z=-10),VerticalState(0),4,others=[other])
    assert state.z<=-4.39
    other=world.car_box(VehicleState(),VerticalState(5))
    state,_,_=drive(world,VehicleState(z=-10),VerticalState(0),4,others=[other])
    assert state.z>10


def test_real_map_underpass_and_all_curved_ramps_remain_driveable():
    import json
    from pathlib import Path
    nav=json.loads((Path(__file__).resolve().parents[2]/'client/public/content/world/navigation.json').read_text())
    world=VehicleWorld(nav['surfaces'],nav['colliders'],nav['ceilings'])
    bridge=next(r for r in nav['sourceRoads'] if r['asset']=='road-bridge')
    routes=[(r,r['ports']) for r in nav['sourceRoads'] if r['asset']=='road-slant-flat-curve']
    routes.extend((bridge,[p for p in bridge['ports'] if p['group']==level]) for level in ['lower','upper'])
    for road,ports in routes:
        for a,b in [ports,list(reversed(ports))]:
            x0,z0=-a['position'][0],-a['position'][1]
            x1,z1=-b['position'][0],-b['position'][1]
            heading=math.atan2(x1-x0,z1-z0)
            state=VehicleState(x=x0,z=z0,heading=heading,speed=3)
            body=world.restore(x0,z0,heading,a['position'][2])
            count=math.ceil(math.hypot(x1-x0,z1-z0)/.1)
            for index in range(1,count+1):
                t=index/count;x,z=x0+(x1-x0)*t,z0+(z1-z0)*t
                candidate=replace(state,x=x,z=z,heading=heading,speed=3)
                state,body=world.step(state,candidate,body,1/30)
                assert math.hypot(state.x-x,state.z-z)<.03,road['object']
                assert body.grounded,road['object']
            assert abs(body.y-b['position'][2])<.05,road['object']


def test_raised_curb_cannot_be_stepped_over_or_crossed_at_extreme_speed():
    curb={**box(z=0,width=30,length=.04,bottom=0,top=2.7),'kind':'curb'}
    world=VehicleWorld(floor(.1),[curb])
    start=VehicleState(z=-10,speed=100)
    state,body=world.step(start,replace(start,z=10),VerticalState(.1),.1)
    assert state.z < -2.2
    assert body.y==pytest.approx(.1)
    assert penetration(state.x,state.z,state.heading,curb) is None


def test_real_map_curbs_hold_the_car_and_port_openings_stay_clear():
    import json
    from pathlib import Path
    nav=json.loads((Path(__file__).resolve().parents[2]/'client/public/content/world/navigation.json').read_text())
    world=VehicleWorld(nav['surfaces'],nav['colliders'],nav['ceilings'])
    assert any(b.get('kind')=='curb' for b in nav['colliders'])
    for road in nav['sourceRoads']:
        if road['asset']!='road-straight' or road['position'][2]!=0:continue
        a,b=road['ports'];dx=b['position'][0]-a['position'][0];dz=b['position'][1]-a['position'][1]
        lane_heading=math.atan2(-dx,-dz)
        for side in [-1,1]:
            start=VehicleState(x=-road['position'][0],z=-road['position'][1],heading=lane_heading+side*math.pi/2,speed=22)
            body=world.restore(start.x,start.z,start.heading,.1)
            state,body,_=drive(world,start,body,.4)
            # В Kenney straight внутренний бордюр в 4 м от оси: весь кузов остаётся внутри.
            assert math.hypot(state.x-start.x,state.z-start.z)+CAR_LENGTH/2 <= 4,road['object']
            assert abs(state.speed)<.01,road['object']
    # Боксы боковин не должны закрывать сквозные стыки прямых модулей.
    start=VehicleState(x=58.5,z=40,heading=math.pi)
    state,body,_=drive(world,start,VerticalState(.1),3)
    assert state.z<25
    assert body.grounded
