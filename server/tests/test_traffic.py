import json
import math
import unittest
from pathlib import Path
from server.traffic import WorldTraffic, TrafficCar, overlap
from server.vehicle import VehicleState
from server.world_physics import VerticalState, VehicleWorld
from server.road_surface import RoadSurface


class TrafficTests(unittest.TestCase):
    def crossing(self, left=False):
        points={'O':(0,0),'S':(0,-10),'N':(0,10),'E':(10,0),'W':(-10,0)}
        edges=[(a,b) for a in points for b in points if a!=b and ('O' in (a,b))]
        lanes=[dict(id=f'{a}>{b}',centerline=[dict(x=points[p][0],z=points[p][1],y=.1) for p in (a,b)],
                    nextLaneIds=[f'{b}>{c}' for c in points if (c!=a or b!='O') and (b,c) in edges]) for a,b in edges]
        traffic=WorldTraffic(lanes,count=0)
        own=TrafficCar('south','sedan','S>O','O>W' if left else 'O>N',4)
        peer=TrafficCar('north' if left else 'east','sedan','N>O' if left else 'E>O','O>S' if left else 'O>W',4)
        traffic.cars=[own,peer]
        for car in traffic.cars: traffic._route(car);traffic._place(car)
        return traffic,own,peer

    def test_yields_to_vehicle_on_right(self):
        traffic,own,peer=self.crossing()
        traffic.step(1/30)
        self.assertEqual(traffic.owners['O'],peer.id)
        self.assertEqual(own.speed,0)

    def test_left_turn_yields_to_oncoming_vehicle(self):
        traffic,own,peer=self.crossing(left=True)
        traffic.step(1/30)
        self.assertEqual(traffic.owners['O'],peer.id)
        self.assertEqual(own.speed,0)

    @classmethod
    def setUpClass(cls):
        cls.navigation=json.loads((Path(__file__).resolve().parents[2]/'client/public/content/world/navigation.json').read_text())
        cls.lanes=cls.navigation['lanes']

    def road_traffic(self, count=0):
        return WorldTraffic(self.lanes,count=count,source_roads=self.navigation['sourceRoads'])

    def road_route(self, traffic, a, b, c):
        car=TrafficCar('route','sedan',a+'>'+b,b+'>'+c,4)
        traffic._route(car)
        return car

    def test_straight_through_t_junction_stays_in_its_lane(self):
        traffic=self.road_traffic()
        south=self.road_route(traffic,'Compact_002_road-straight:all','Compact_003_road-intersection-path:all','Compact_004_road-straight:all')
        north=self.road_route(traffic,'Compact_004_road-straight:all','Compact_003_road-intersection-path:all','Compact_002_road-straight:all')
        for p in south.path: self.assertAlmostEqual(p[0],58.5)
        for p in north.path: self.assertAlmostEqual(p[0],61.5)

    def test_opposing_bend_routes_are_separate_concentric_lanes(self):
        traffic=self.road_traffic()
        outer=self.road_route(traffic,'Compact_001_road-straight:all','Compact_000_road-bend:all','Compact_013_road-straight:all')
        inner=self.road_route(traffic,'Compact_013_road-straight:all','Compact_000_road-bend:all','Compact_001_road-straight:all')
        for p in outer.path: self.assertAlmostEqual(math.hypot(p[0]-55,p[2]-45),6.5,places=4)
        for p in inner.path: self.assertAlmostEqual(math.hypot(p[0]-55,p[2]-45),3.5,places=4)
        self.assertGreaterEqual(min(math.dist(a,b) for a in outer.path for b in inner.path),2.999)

    def test_all_ground_routes_have_exact_stitches_and_road_support(self):
        traffic=self.road_traffic()
        surface=RoadSurface(self.navigation['surfaces'])
        self.assertEqual(len(traffic.ports),len(traffic.lanes))
        for lane in traffic.lanes.values():
            for nxt in lane['nextLaneIds']:
                car=TrafficCar('route','sedan',lane['id'],nxt,4);traffic._route(car)
                following=TrafficCar('next','sedan',nxt,traffic.lanes[nxt]['nextLaneIds'][0],4);traffic._route(following)
                self.assertLess(math.dist(car.path[-1],following.path[0]),1e-4)
                for p in car.path:
                    self.assertTrue(any(abs(h-p[1])<.2 for h,_ in surface.contacts(p[0],p[2],0)),(lane['id'],nxt,p))

    def test_scenarios_never_receive_npcs(self):
        traffic=self.road_traffic(count=1)
        self.assertEqual(len(traffic.snapshot('world')),1)
        self.assertEqual(traffic.snapshot('scenario'),[])

    def test_ten_minutes_without_overlap_heading_snap_or_gridlock(self):
        traffic=self.road_traffic(count=10)
        moved=0
        recent={c.id:0. for c in traffic.cars}
        for step in range(18000):
            before={c.id:(c.x,c.z,c.heading) for c in traffic.cars}
            traffic.step(1/30)
            for i,car in enumerate(traffic.cars):
                x,z,h=before[car.id]
                moved+=math.hypot(car.x-x,car.z-z)
                if step>=17100: recent[car.id]+=math.hypot(car.x-x,car.z-z)
                self.assertLessEqual(abs(math.atan2(math.sin(car.heading-h),math.cos(car.heading-h))),1.4/30+1e-6)
                for other in traffic.cars[i+1:]: self.assertFalse(overlap(traffic.box(car),traffic.box(other)))
        self.assertGreater(moved,100)
        for distance in recent.values(): self.assertGreater(distance,5)

    def test_player_impact_stops_npc_for_five_seconds(self):
        traffic=WorldTraffic(self.lanes,count=1)
        car=traffic.cars[0]
        player=VehicleState(car.x,car.z,car.heading,speed=5)
        traffic.player_contact(player,player,VerticalState(y=car.y))
        self.assertTrue(car.crashed)
        position=(car.x,car.z)
        for _ in range(149): traffic.step(1/30)
        self.assertEqual(position,(car.x,car.z))
        self.assertEqual(car.speed,0)
        traffic.step(1/30)
        self.assertFalse(car.crashed)
        self.assertNotEqual(position,(car.x,car.z))

    def test_contact_does_not_reset_timer_but_player_still_blocks_departure(self):
        traffic=WorldTraffic(self.lanes,count=1)
        car=traffic.cars[0]
        player=VehicleState(car.x,car.z,car.heading)
        body=VerticalState(y=car.y)
        traffic.player_contact(player,player,body)
        for _ in range(180):
            traffic.step(1/30,[VehicleWorld.car_box(player,body)])
            traffic.player_contact(player,player,body)
        self.assertLess(car.stop_remaining,1e-9)
        self.assertTrue(car.crashed)
        traffic.step(1/30)
        self.assertFalse(car.crashed)
        self.assertGreater(car.speed,0)

    def test_bridge_level_does_not_trigger_collision(self):
        traffic=WorldTraffic(self.lanes,count=1)
        car=traffic.cars[0]
        player=VehicleState(car.x,car.z,car.heading)
        traffic.player_contact(player,player,VerticalState(y=car.y+5))
        self.assertFalse(car.crashed)

    def test_frozen_npc_remains_a_solid_body(self):
        traffic=WorldTraffic(self.lanes,count=1)
        car=traffic.cars[0];car.crashed=True
        self.assertEqual(traffic.boxes()[0]['halfLength'],1.65)
        self.assertTrue(overlap(traffic.box(car),traffic.boxes()[0]))

    def test_swept_player_impact_is_resolved_by_physics(self):
        traffic=WorldTraffic(self.lanes,count=1)
        car=traffic.cars[0]
        dx,dz=math.sin(car.heading),math.cos(car.heading)
        previous=VehicleState(car.x-dx*8,car.z-dz*8,car.heading,speed=20)
        proposed=VehicleState(car.x+dx*8,car.z+dz*8,car.heading,speed=20)
        body=VerticalState(y=car.y)
        traffic.player_contact(previous,proposed,body)
        world=VehicleWorld([],ground_y=car.y)
        resolved,vertical=world.step(previous,proposed,body,1/30,traffic.boxes())
        self.assertTrue(car.crashed)
        self.assertFalse(overlap(world.car_box(resolved,vertical),traffic.box(car)))
        self.assertLess((resolved.x-car.x)*dx+(resolved.z-car.z)*dz,0)
