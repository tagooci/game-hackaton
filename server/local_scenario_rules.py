"""Geometry-based checks for the two new scenarios; never trusts client results."""
import math
from itertools import combinations
from .world_physics import CAR_HEIGHT, CAR_WIDTH, CAR_LENGTH, penetration


def project(route, x, z):
    best = (float('inf'), 0., 0.)
    along = 0.
    for a,b in zip(route,route[1:]):
        dx,dz=b[0]-a[0],b[1]-a[1]
        length=math.hypot(dx,dz)
        if length < 1e-8: continue
        t=max(0.,min(1.,((x-a[0])*dx+(z-a[1])*dz)/(length*length)))
        distance=math.hypot(x-a[0]-t*dx,z-a[1]-t*dz)
        if distance < best[0]: best=(distance,along+t*length,math.atan2(dx,dz))
        along+=length
    return (*best,along)


def violation(player, text):
    errors=player.setdefault('scenario_errors',[])
    if text not in errors: errors.append(text)
    player['scenario_result']='Нарушения: '+'; '.join(errors)


def check_new_passage(session, players, definition, world):
    active=[players[pid] for pid in session['players'] if pid in players and pid not in session.get('finished',set()) and players[pid]['sceneId']==session['id']]
    roles={r['id']:r for r in definition['roles']}
    tracks=session.setdefault('tracks',{})
    for player in active:
        state=player['vehicle'];role=roles[player['roleId']]
        distance,progress,heading,total=project(role['route'],state.x,state.z)
        track=tracks.setdefault(player['id'],dict(progress=0.,maxProgress=0.,entered=player['roleId']=='ring-north'))
        # Ordered progress prevents skipping the island or taking a wrong exit then returning.
        if progress > track['maxProgress']+6:
            violation(player,'пропущена часть маршрута')
        else: track['maxProgress']=max(track['maxProgress'],progress)
        if distance > (3.0 if definition['kind']=='roundabout' else 1.5):
            violation(player,'неверная полоса или выезд')
        if distance < 2.5 and state.speed > .8 and math.cos(state.heading-heading) < -.25:
            violation(player,'движение против направления маршрута')
        track.update(progress=progress,total=total)
    for a,b in combinations(active,2):
        box=world.car_box(b['vehicle'],b['vertical'])
        box['halfWidth']+=.03;box['halfLength']+=.03
        if abs(a['vertical'].y-b['vertical'].y)<CAR_HEIGHT and penetration(a['vehicle'].x,a['vehicle'].z,a['vehicle'].heading,box):
            violation(a,'столкновение');violation(b,'столкновение')
    if definition['kind']=='equal':
        check_equal(active, definition, tracks)
    elif definition['kind']=='roundabout':
        check_ring(active, definition, tracks)
    else:
        check_junction(active, definition, tracks)


def check_equal(players, definition, tracks):
    cx,cz=definition['center']
    for player in players:
        s=player['vehicle'];track=tracks[player['id']]
        in_center=abs(s.x-cx)<5.8 and abs(s.z-cz)<5.8
        if in_center and not track.get('entered'):
            for other in players:
                if other['roleId'] not in definition['yieldsTo'].get(player['roleId'],[]): continue
                t=tracks[other['id']];o=other['vehicle']
                # Only traffic still approaching or occupying the conflict area matters.
                if t.get('cleared'):continue
                dx,dz=o.x-cx,o.z-cz
                toward=-(dx*math.sin(o.heading)+dz*math.cos(o.heading))
                arrival=max(0.,math.hypot(dx,dz)-5)/max(abs(o.speed),.5)
                own_clear=(8+CAR_LENGTH)/max(abs(s.speed),2.)
                if (abs(dx)<6 and abs(dz)<6) or (toward>0 and o.speed>.5 and arrival<own_clear):
                    violation(player,'не уступили автомобилю с преимуществом')
            track['entered']=True
        # Re-evaluate during traversal, not only on first wheel over a boundary.
        if in_center:
            for other in players:
                if other['roleId'] in definition['yieldsTo'].get(player['roleId'],[]) and not tracks[other['id']].get('cleared'):
                    o=other['vehicle']
                    if math.hypot(o.x-s.x,o.z-s.z)<5 and o.speed>.5:
                        violation(player,'не уступили автомобилю с преимуществом')
        if track.get('entered') and not in_center: track['cleared']=True


def check_ring(players, definition, tracks):
    cx,cz=definition['center']
    for player in players:
        s=player['vehicle'];track=tracks[player['id']]
        radius=math.hypot(s.x-cx,s.z-cz)
        if radius < 12 and not track['entered']:
            angle=math.atan2(s.z-cz,s.x-cx)
            for other in players:
                if other is player or not tracks[other['id']].get('entered'):continue
                o=other['vehicle'];r=math.hypot(o.x-cx,o.z-cz)
                if not 6<r<12.5:continue
                delta=(angle-math.atan2(o.z-cz,o.x-cx))%(2*math.pi)
                gap=delta*10
                if gap<5 or (o.speed>.5 and gap/o.speed<2.5):
                    violation(player,'не уступили при въезде на круг')
            track['entered']=True
        if 6<radius<12 and s.speed>.5:
            theta=math.atan2(s.z-cz,s.x-cx)
            tangent=(-math.sin(theta),math.cos(theta))
            if math.sin(s.heading)*tangent[0]+math.cos(s.heading)*tangent[1]<-.3:
                violation(player,'движение по кругу в обратную сторону')


def finished_route(player, session):
    track=session.get('tracks',{}).get(player['id'])
    return bool(track and track['maxProgress']>=track['total']-4)


_CONFLICT_WINDOWS = {}

def conflict_windows(definition):
    """Shared swept-route regions, including an outbound merge; opposite lanes do not conflict."""
    key=definition['id']
    if key in _CONFLICT_WINDOWS:return _CONFLICT_WINDOWS[key]
    roles={r['id']:r for r in definition['roles']}
    result={}
    for own,priorities in definition.get('yieldsTo',{}).items():
        route=roles[own]['route'];own_lengths=[0.]
        for a,b in zip(route,route[1:]):own_lengths.append(own_lengths[-1]+math.dist(a,b))
        for other in priorities:
            peer_route=roles[other]['route'];peer_lengths=[0.]
            for a,b in zip(peer_route,peer_route[1:]):peer_lengths.append(peer_lengths[-1]+math.dist(a,b))
            near=[(own_lengths[i],peer_lengths[j]) for i,a in enumerate(route) for j,b in enumerate(peer_route) if math.dist(a,b)<2.2]
            if near:
                result[own,other]=(max(0,min(a for a,b in near)-CAR_LENGTH/2),max(a for a,b in near)+CAR_LENGTH/2,
                                   max(0,min(b for a,b in near)-CAR_LENGTH/2),max(b for a,b in near)+CAR_LENGTH/2)
    _CONFLICT_WINDOWS[key]=result
    return result


def check_junction(players,definition,tracks):
    windows=conflict_windows(definition)
    by_role={p['roleId']:p for p in players}
    for player in players:
        state=player['vehicle'];track=tracks[player['id']]
        for priority in definition.get('yieldsTo',{}).get(player['roleId'],[]):
            other=by_role.get(priority);window=windows.get((player['roleId'],priority))
            if not other or not window:continue
            start,end,other_start,other_end=window
            if not start<=track['progress']<=end or state.speed<=.35:continue
            checked=track.setdefault('priority_checked',set())
            if priority in checked:continue
            checked.add(priority)
            peer=tracks[other['id']];o=other['vehicle']
            if peer['progress']>other_end:continue
            distance=max(0,other_start-peer['progress'])
            clear_time=min(4.,max(.8,(end-track['progress'])/max(state.speed,2.)))
            occupying=other_start<=peer['progress']<=other_end
            approaching=o.speed>.5 and distance/o.speed<clear_time
            if occupying or approaching:
                violation(player,'не уступили автомобилю с преимуществом')
