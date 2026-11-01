"""Shared-world traffic; deterministic routes, reservations and physical bodies."""
from dataclasses import dataclass, field
from bisect import bisect_right
import math
import random

MODELS = {'sedan':3.3, 'sedan-sports':3.3, 'suv':3.5, 'taxi':3.3,
          'van':3.6, 'truck':4.0, 'ambulance':3.6, 'police':3.3, 'firetruck':4.0}


def overlap(a, b, margin=0):
    if a['minY'] >= b['maxY'] or b['minY'] >= a['maxY']: return False
    axes = lambda h: ((math.cos(h),-math.sin(h)),(math.sin(h),math.cos(h)))
    aa,bb=axes(a['heading']),axes(b['heading'])
    for nx,nz in (*aa,*bb):
        radius=lambda box,ax: abs(nx*ax[0][0]+nz*ax[0][1])*(box['halfWidth']+margin)+abs(nx*ax[1][0]+nz*ax[1][1])*(box['halfLength']+margin)
        if abs((a['x']-b['x'])*nx+(a['z']-b['z'])*nz) >= radius(a,aa)+radius(b,bb): return False
    return True


@dataclass
class TrafficCar:
    id: str
    model: str
    lane_id: str
    next_lane_id: str
    cruise: float
    distance: float = 0
    speed: float = 0
    x: float = 0
    y: float = .1
    z: float = 0
    heading: float = 0
    pitch: float = 0
    crashed: bool = False
    stop_remaining: float = 0
    waiting: float = 0
    path: list = field(default_factory=list)
    lengths: list = field(default_factory=list)


class WorldTraffic:
    def __init__(self, lanes, count=10, seed=7319, surface=None, source_roads=()):
        # Elevated importer nodes do not describe the deck's real lane curves.
        # Keep ambient traffic on the validated ground network until those
        # centerlines are exported, rather than routing through bridge edges.
        self.lanes={lane['id']:dict(lane) for lane in lanes
                    if max(p['y'] for p in lane['centerline'])<.5}
        for lane in self.lanes.values():
            lane['nextLaneIds']=[key for key in lane['nextLaneIds'] if key in self.lanes]
        while any(not lane['nextLaneIds'] for lane in self.lanes.values()):
            self.lanes={key:lane for key,lane in self.lanes.items() if lane['nextLaneIds']}
            for lane in self.lanes.values():
                lane['nextLaneIds']=[key for key in lane['nextLaneIds'] if key in self.lanes]
        self.random=random.Random(seed)
        self.surface=surface
        self.ports={}
        roads={road['object']:road for road in source_roads}
        def ports(node):
            name,_,group=node.rpartition(':')
            return [p for p in roads.get(name,{}).get('ports',()) if p.get('group','all') in ('all',group)]
        for lane_id in self.lanes:
            origin,destination=lane_id.split('>')
            matches=[(a,b) for a in ports(origin) for b in ports(destination)
                     if math.dist(a['position'],b['position'])<.15]
            if matches:
                p=matches[0][1]
                self.ports[lane_id]=dict(x=-p['position'][0],y=p['position'][2],z=-p['position'][1],
                                         dx=-p['direction'][0],dz=-p['direction'][1])
        self.cars=[]
        self.owners={}
        valid=[key for key,lane in self.lanes.items() if lane['nextLaneIds']]
        if not valid: return
        for index in range(count):
            for _ in range(300):
                lane=self.random.choice(valid)
                car=TrafficCar(f'traffic-{index+1:02}',list(MODELS)[index%len(MODELS)],lane,
                               self.random.choice(self.lanes[lane]['nextLaneIds']), self.random.uniform(3.4,5))
                self._route(car)
                self._place(car)
                if not any(overlap(self.box(car),self.box(other),1.5) or self._junction(car)==self._junction(other)
                           for other in self.cars): break
            else: continue
            self.cars.append(car)

    def _junction(self, car): return car.lane_id.split('>')[-1]

    def _route(self, car):
        a,b=self.lanes[car.lane_id]['centerline'][::len(self.lanes[car.lane_id]['centerline'])-1]
        c=self.lanes[car.next_lane_id]['centerline'][-1]
        def direction(p,q):
            length=math.hypot(q['x']-p['x'],q['z']-p['z'])
            return ((q['x']-p['x'])/length,(q['z']-p['z'])/length)
        u,v=direction(a,b),direction(b,c)
        offset=1.5
        start=((a['x']+b['x'])/2+u[1]*offset,(a['y']+b['y'])/2,(a['z']+b['z'])/2-u[0]*offset)
        end=((b['x']+c['x'])/2+v[1]*offset,(b['y']+c['y'])/2,(b['z']+c['z'])/2-v[0]*offset)
        if car.lane_id in self.ports and car.next_lane_id in self.ports:
            entry=self.ports[car.lane_id]
            # The following lane stores its destination's outward port normal;
            # it points back into this road, hence the sign reversal on exit.
            exit=self.ports[car.next_lane_id]
            u=(-entry['dx'],-entry['dz'])
            v=(-exit['dx'],-exit['dz'])
            start=(entry['x']+u[1]*offset,entry['y'],entry['z']-u[0]*offset)
            end=(exit['x']+v[1]*offset,exit['y'],exit['z']-v[0]*offset)
        # Intersection of the two offset lane tangents gives a quadratic curve
        # whose derivatives agree with the neighbouring route at each midpoint.
        det=u[0]*v[1]-u[1]*v[0]
        if abs(det)>.05:
            t=((end[0]-start[0])*v[1]-(end[2]-start[2])*v[0])/det
            control=(start[0]+t*u[0],b['y'],start[2]+t*u[1])
        else: control=tuple((start[j]+end[j])/2 for j in range(3))
        car.path=[]
        for i in range(41):
            t=i/40
            p=tuple((1-t)**2*start[j]+2*t*(1-t)*control[j]+t*t*end[j] for j in range(3))
            car.path.append(p)
        turn=math.atan2(u[1]*v[0]-u[0]*v[1],u[0]*v[0]+u[1]*v[1])
        if abs(abs(turn)-math.pi/2)<.01:
            incoming=math.hypot(control[0]-start[0],control[2]-start[2])
            outgoing=math.hypot(control[0]-end[0],control[2]-end[2])
            if incoming>0 and abs(incoming-outgoing)<.05:
                sign=1 if turn>0 else -1
                cx,cz=start[0]+sign*u[1]*incoming,start[2]-sign*u[0]*incoming
                angle=math.atan2(start[2]-cz,start[0]-cx)
                car.path=[(cx+incoming*math.cos(angle-turn*i/60),
                           start[1]+(end[1]-start[1])*i/60,
                           cz+incoming*math.sin(angle-turn*i/60)) for i in range(61)]
        if 'roundabout' in self._junction(car):
            radius=4.5
            angle_a=math.atan2(start[2]-b['z'],start[0]-b['x'])+.4
            angle_b=math.atan2(end[2]-b['z'],end[0]-b['x'])-.4
            while angle_b<angle_a: angle_b+=2*math.pi
            ring=lambda angle:(b['x']+radius*math.cos(angle),b['y'],b['z']+radius*math.sin(angle))
            entry,exit=ring(angle_a),ring(angle_b)
            tangent=lambda angle:(-math.sin(angle),0,math.cos(angle))
            def cubic(p,q,r,s):
                return [tuple((1-t)**3*p[j]+3*t*(1-t)**2*q[j]+3*t*t*(1-t)*r[j]+t**3*s[j] for j in range(3)) for t in [i/20 for i in range(21)]]
            et,xt=tangent(angle_a),tangent(angle_b)
            car.path=cubic(start,(start[0]+u[0]*1.2,start[1],start[2]+u[1]*1.2),
                           tuple(entry[j]-et[j]*1.2 for j in range(3)),entry)
            car.path.extend(ring(angle_a+(angle_b-angle_a)*i/60) for i in range(1,61))
            car.path.extend(cubic(exit,tuple(exit[j]+xt[j]*1.2 for j in range(3)),
                                  (end[0]-v[0]*1.2,end[1],end[2]-v[1]*1.2),end)[1:])
        car.lengths=[0.]
        for p,q in zip(car.path,car.path[1:]): car.lengths.append(car.lengths[-1]+math.dist(p,q))
        car.distance=0

    def _place(self, car, dt=None):
        i=min(len(car.path)-2,max(0,bisect_right(car.lengths,car.distance)-1))
        a,b=car.path[i:i+2]
        t=(car.distance-car.lengths[i])/max(1e-8,car.lengths[i+1]-car.lengths[i])
        car.x,car.y,car.z=(a[j]+(b[j]-a[j])*t for j in range(3))
        heading=math.atan2(b[0]-a[0],b[2]-a[2])
        if dt is not None:
            change=math.atan2(math.sin(heading-car.heading),math.cos(heading-car.heading))
            heading=car.heading+max(-1.4*dt,min(1.4*dt,change))
        car.heading=heading
        car.pitch=-math.atan2(b[1]-a[1],math.hypot(b[0]-a[0],b[2]-a[2]))
        if self.surface:
            contacts=self.surface.contacts(car.x,car.z,car.heading)
            if contacts: car.y,car.pitch=min(contacts,key=lambda p:abs(p[0]-car.y))

    @staticmethod
    def box(car):
        return dict(x=car.x,z=car.z,heading=car.heading,halfWidth=.95,
                    halfLength=MODELS[car.model]/2,minY=car.y,
                    maxY=car.y+(2.2 if car.model in ('truck','firetruck') else 1.7))

    def boxes(self): return [self.box(car) for car in self.cars]

    def player_contact(self, previous, proposed, body):
        """Swept contact before the existing player solver separates bodies."""
        steps=max(1,math.ceil(math.hypot(proposed.x-previous.x,proposed.z-previous.z)/.1))
        for i in range(steps+1):
            t=i/steps
            box=dict(x=previous.x+(proposed.x-previous.x)*t,z=previous.z+(proposed.z-previous.z)*t,
                     heading=proposed.heading,halfWidth=.975,halfLength=1.65,minY=body.y,maxY=body.y+1.6875)
            for car in self.cars:
                if overlap(box,self.box(car),.025) and not car.crashed:
                    car.crashed=True
                    car.stop_remaining=5.0
                    car.speed=0

    def step(self, dt, players=()):
        if not math.isfinite(dt) or not 0<dt<=.1: raise ValueError('Invalid traffic dt')
        # A reservation is retained through the whole turn, including an exit
        # blocked by a queue. Thus a second vehicle cannot drive into its side.
        for car in self.cars:
            if car.crashed:
                car.speed=0
                car.stop_remaining=max(0,car.stop_remaining-dt)
                if car.stop_remaining>1e-9 or any(overlap(self.box(car),p,.15) for p in players):
                    continue
                car.crashed=False
            key=self._junction(car)
            junction=len(self.lanes[car.lane_id]['nextLaneIds'])>1
            blocked=False
            if junction and self.owners.get(key) not in (None,car.id): blocked=True
            if junction and key not in self.owners:
                contenders=[other for other in self.cars if not other.crashed and self._junction(other)==key]
                # Equal priority: yield to the approach on the right and to
                # opposing traffic when turning left. ID breaks circular ties.
                def threats(own):
                    a,b=self.lanes[own.lane_id]['centerline'][0],self.lanes[own.lane_id]['centerline'][-1]
                    h=math.atan2(b['x']-a['x'],b['z']-a['z'])
                    c=self.lanes[own.next_lane_id]['centerline'][-1]
                    turn=math.atan2(math.sin(math.atan2(c['x']-b['x'],c['z']-b['z'])-h),
                                    math.cos(math.atan2(c['x']-b['x'],c['z']-b['z'])-h))
                    count=0
                    for other in contenders:
                        if other is own: continue
                        right=(other.x-own.x)*math.cos(h)-(other.z-own.z)*math.sin(h)>1
                        opposite=math.cos(other.heading-h)<-.7
                        count+=right or (turn<-.3 and opposite)
                    return count
                winner=min(contenders,key=lambda c:(threats(c),-c.waiting,c.id)) if contenders else car
                if winner is car and not blocked: self.owners[key]=car.id
                else: blocked=True
            target=0 if blocked else car.cruise
            a,b=self.lanes[car.lane_id]['centerline'][0],self.lanes[car.lane_id]['centerline'][-1]
            c=self.lanes[car.next_lane_id]['centerline'][-1]
            turn=math.atan2(c['x']-b['x'],c['z']-b['z'])-math.atan2(b['x']-a['x'],b['z']-a['z'])
            if abs(math.atan2(math.sin(turn),math.cos(turn)))>.35: target=min(target,2.3)
            if 'roundabout' in key: target=min(target,2)
            stop_at=car.lengths[-1]
            if junction and car.distance<car.lengths[-1]*.45:
                h=math.atan2(b['x']-a['x'],b['z']-a['z'])
                for player in players:
                    dx,dz=b['x']-player['x'],b['z']-player['z']
                    approaching=dx*math.sin(player['heading'])+dz*math.cos(player['heading'])
                    right=(player['x']-car.x)*math.cos(h)-(player['z']-car.z)*math.sin(h)>1
                    opposite=math.cos(player['heading']-h)<-.7
                    left=math.atan2(math.sin(turn),math.cos(turn))<-.3
                    if (abs(player['minY']-car.y)<2 and math.hypot(dx,dz)<12 and approaching>0
                            and (right or (left and opposite))): target=0
            obstacles=[self.box(other) for other in self.cars if other is not car]+list(players)
            # Speed-dependent following distance, including stationary wrecks.
            for box in obstacles:
                dx,dz=box['x']-car.x,box['z']-car.z
                ahead=dx*math.sin(car.heading)+dz*math.cos(car.heading)
                side=abs(dx*math.cos(car.heading)-dz*math.sin(car.heading))
                aligned=math.cos(box['heading']-car.heading)
                projected_length=abs(aligned)*box['halfLength']+abs(math.sin(box['heading']-car.heading))*box['halfWidth']
                gap=ahead-MODELS[car.model]/2-projected_length
                if abs(box['minY']-car.y)<2 and aligned>.6 and ahead>0 and side<1.8 and gap<2+car.speed*1.3:
                    target=min(target,max(0,(gap-1)/1.3))
            car.waiting=car.waiting+dt if target<.1 else 0
            old=(car.distance,car.x,car.y,car.z,car.heading,car.pitch)
            car.speed=min(target,car.speed+1.6*dt)
            car.distance=min(stop_at,car.distance+car.speed*dt)
            self._place(car,dt)
            if any(overlap(self.box(car),box,.15) for box in obstacles):
                car.distance,car.x,car.y,car.z,car.heading,car.pitch=old
                car.speed=0
            if car.distance>=car.lengths[-1]-1e-6:
                if self.owners.get(key)==car.id: self.owners.pop(key)
                car.lane_id=car.next_lane_id
                car.next_lane_id=self.random.choice(self.lanes[car.lane_id]['nextLaneIds'])
                self._route(car)
                self._place(car,0)

    def snapshot(self, scene_kind='world'):
        if scene_kind!='world': return []
        return [dict(id=c.id,model=c.model,x=round(c.x,3),y=round(c.y,4),z=round(c.z,3),
                     heading=round(c.heading,4),pitch=round(c.pitch,4),speed=round(c.speed,3)) for c in self.cars]
