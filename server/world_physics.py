"""Серверные контакты автомобиля: ориентированные боксы, опора и гравитация."""
from dataclasses import dataclass, replace
from collections import defaultdict
import math

from .road_surface import RoadSurface

CAR_WIDTH = 2.6
CAR_LENGTH = 4.4
CAR_HEIGHT = 2.25
STEP_HEIGHT = .16
GRAVITY = 9.81


@dataclass(frozen=True)
class VerticalState:
    y: float = 0.0
    velocity: float = 0.0
    pitch: float = 0.0
    grounded: bool = True


def axes(heading):
    return ((math.cos(heading),-math.sin(heading)),(math.sin(heading),math.cos(heading)))


def inside(box, x, z):
    right, forward = axes(box['heading'])
    dx,dz = x-box['x'],z-box['z']
    return abs(dx*right[0]+dz*right[1]) <= box['halfWidth'] and abs(dx*forward[0]+dz*forward[1]) <= box['halfLength']


def penetration(x,z,heading,box):
    """SAT: минимальное горизонтальное смещение двух ориентированных боксов."""
    own,other = axes(heading),axes(box['heading'])
    smallest = None
    for nx,nz in (*own,*other):
        own_radius = abs(nx*own[0][0]+nz*own[0][1])*CAR_WIDTH/2 + abs(nx*own[1][0]+nz*own[1][1])*CAR_LENGTH/2
        other_radius = abs(nx*other[0][0]+nz*other[0][1])*box['halfWidth'] + abs(nx*other[1][0]+nz*other[1][1])*box['halfLength']
        separation = (x-box['x'])*nx+(z-box['z'])*nz
        overlap = own_radius+other_radius-abs(separation)
        if overlap <= 0:
            return None
        if smallest is None or overlap < smallest[0]:
            sign = 1 if separation >= 0 else -1
            smallest = overlap,nx*sign,nz*sign
    return smallest


class VehicleWorld:
    def __init__(self,surfaces,boxes=(),ceilings=(),ground_y=-.12):
        self.surface = RoadSurface(surfaces)
        self.ceiling = RoadSurface(ceilings)
        self.ground_y = ground_y
        self.boxes = list(boxes)
        self.cells = defaultdict(list)
        for index,box in enumerate(self.boxes):
            radius = math.hypot(box['halfWidth'],box['halfLength'])
            for x in range(math.floor((box['x']-radius)/10),math.floor((box['x']+radius)/10)+1):
                for z in range(math.floor((box['z']-radius)/10),math.floor((box['z']+radius)/10)+1):
                    self.cells[x,z].append(index)

    def nearby(self,x,z):
        indices = set()
        for cx in range(math.floor((x-3)/10),math.floor((x+3)/10)+1):
            for cz in range(math.floor((z-3)/10),math.floor((z+3)/10)+1):
                indices.update(self.cells.get((cx,cz),()))
        return [self.boxes[index] for index in sorted(indices)]

    @staticmethod
    def car_box(state,body):
        return dict(x=state.x,z=state.z,heading=state.heading,halfWidth=CAR_WIDTH/2,halfLength=CAR_LENGTH/2,
                    minY=body.y,maxY=body.y+CAR_HEIGHT)

    def floors(self,x,z,heading,boxes):
        contacts = [(self.ground_y,0.0),*self.surface.contacts(x,z,heading)]
        contacts.extend((box['maxY'],0.0) for box in boxes if box.get('kind') != 'curb' and inside(box,x,z))
        return contacts

    def restore(self,x,z,heading,y):
        """Сохранённая высота не заменяется ближайшим этажом моста."""
        y = max(y,self.ground_y)
        contacts = self.floors(x,z,heading,self.nearby(x,z))
        close = [(h,p) for h,p in contacts if abs(h-y) <= .04]
        if close:
            h,p = min(close,key=lambda contact:abs(contact[0]-y))
            return VerticalState(h,pitch=p)
        return VerticalState(y,grounded=False)

    def ceiling_overlap(self,state,body):
        right,forward = axes(state.heading)
        for sideways,longitudinal in [(0,0),(-CAR_WIDTH/2,-CAR_LENGTH/2),(-CAR_WIDTH/2,CAR_LENGTH/2),
                                      (CAR_WIDTH/2,-CAR_LENGTH/2),(CAR_WIDTH/2,CAR_LENGTH/2)]:
            along = longitudinal*math.cos(body.pitch)
            x = state.x+right[0]*sideways+forward[0]*along
            z = state.z+right[1]*sideways+forward[1]*along
            bottom = body.y-longitudinal*math.sin(body.pitch)
            top = bottom+CAR_HEIGHT*math.cos(body.pitch)
            if any(bottom+.04 < h < top-.02 for h,_ in self.ceiling.contacts(x,z,state.heading)):
                return True
        return False

    def ground_pose(self,state,height,pitch,boxes):
        # Опора под передней и задней осями выравнивает кузов на кривом профиле подъёма.
        axle_heights = []
        for offset in (1.3,-1.3):
            x,z = state.x+math.sin(state.heading)*offset,state.z+math.cos(state.heading)*offset
            expected = height-offset*math.sin(pitch)
            contacts = [(h,p) for h,p in self.floors(x,z,state.heading,boxes) if
                        abs(h-expected) <= STEP_HEIGHT+1.3*abs(math.tan(p))]
            if not contacts:
                return VerticalState(height,pitch=pitch)
            axle_heights.append(min(contacts,key=lambda contact:abs(contact[0]-expected))[0])
        front,rear = axle_heights
        return VerticalState((front+rear)/2,pitch=-math.atan2(front-rear,2.6))

    def vertical_step(self,previous,state,body,dt,boxes):
        contacts = self.floors(state.x,state.z,state.heading,boxes)
        distance = math.hypot(state.x-previous.x,state.z-previous.z)
        if body.grounded:
            previous_contacts = self.floors(previous.x,previous.z,previous.heading,boxes)
            reference = min(previous_contacts,key=lambda contact:abs(contact[0]-body.y))[0]
            if abs(reference-body.y) > .4: reference = body.y
            # Проходим уклон, но не притягиваемся к другому этажу или к земле под обрывом.
            reachable = [(h,p) for h,p in contacts if
                         -.08-distance*abs(math.tan(p)) <= h-reference <= STEP_HEIGHT+distance*abs(math.tan(p))]
            if reachable:
                h,p = min(reachable,key=lambda contact:abs(contact[0]-body.y))
                return self.ground_pose(state,h,p,boxes)
        velocity = body.velocity-GRAVITY*dt
        y = body.y+body.velocity*dt-GRAVITY*dt*dt/2
        crossed = [(h,p) for h,p in contacts if y <= h <= body.y+.001]
        if velocity <= 0 and crossed:
            h,p = max(crossed,key=lambda contact:contact[0])
            return self.ground_pose(state,h,p,boxes)
        return VerticalState(y,velocity,body.pitch,False)

    def step(self,previous,proposed,body,dt,other_cars=()):
        if not body.grounded:
            # В воздухе машина сохраняет горизонтальную скорость и направление.
            proposed = replace(proposed,x=previous.x+math.sin(previous.heading)*previous.speed*dt,
                               z=previous.z+math.cos(previous.heading)*previous.speed*dt,
                               heading=previous.heading,speed=previous.speed)
        dx,dz = proposed.x-previous.x,proposed.z-previous.z
        turn = math.atan2(math.sin(proposed.heading-previous.heading),math.cos(proposed.heading-previous.heading))
        steps = max(1,math.ceil(math.hypot(dx,dz)/.2),math.ceil(abs(turn)/.05))
        state = previous
        collided = False
        for index in range(steps):
            candidate = replace(proposed,x=state.x+dx/steps,z=state.z+dz/steps,
                                heading=previous.heading+turn*(index+1)/steps)
            boxes = [*self.nearby(candidate.x,candidate.z),*other_cars]
            next_body = self.vertical_step(state,candidate,body,dt/steps,boxes)
            if self.ceiling_overlap(candidate,next_body):
                candidate = replace(candidate,x=state.x,z=state.z,heading=state.heading)
                next_body = self.vertical_step(state,candidate,body,dt/steps,boxes)
                collided = True
            for _ in range(4):
                resolved = False
                for box in boxes:
                    # Высота кузова в месте контакта, а не только в его центре:
                    # передний бампер уже поднят, когда машина въезжает с уклона на мост.
                    right,forward = axes(box['heading'])
                    bx,bz = candidate.x-box['x'],candidate.z-box['z']
                    side = max(-box['halfWidth'],min(box['halfWidth'],bx*right[0]+bz*right[1]))
                    along = max(-box['halfLength'],min(box['halfLength'],bx*forward[0]+bz*forward[1]))
                    qx,qz = box['x']+right[0]*side+forward[0]*along,box['z']+right[1]*side+forward[1]*along
                    own_forward = axes(candidate.heading)[1]
                    offset = max(-CAR_LENGTH/2,min(CAR_LENGTH/2,(qx-candidate.x)*own_forward[0]+(qz-candidate.z)*own_forward[1]))
                    bottom = next_body.y-math.tan(next_body.pitch)*offset
                    if bottom >= box['maxY']-.015 or bottom+CAR_HEIGHT <= box['minY']+.015:
                        continue
                    if next_body.grounded and box['maxY'] <= bottom+STEP_HEIGHT:
                        continue
                    hit = penetration(candidate.x,candidate.z,candidate.heading,box)
                    if hit:
                        depth,nx,nz = hit
                        candidate = replace(candidate,x=candidate.x+nx*(depth+.0001),z=candidate.z+nz*(depth+.0001))
                        resolved = collided = True
                if not resolved:
                    break
            # После бокового контакта заново проверяем опору в исправленной позиции.
            if candidate.x != state.x+dx/steps or candidate.z != state.z+dz/steps:
                next_body = self.vertical_step(state,candidate,body,dt/steps,boxes)
            state,body = candidate,next_body
        if collided:
            forward = axes(state.heading)[1]
            direction = 1 if proposed.speed >= 0 else -1
            travelled = ((state.x-previous.x)*forward[0]+(state.z-previous.z)*forward[1])*direction
            speed = direction*min(abs(proposed.speed),max(0,travelled/dt))
            state = replace(state,speed=speed)
        return state,body
