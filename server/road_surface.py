"""Высота и наклон дороги: точные треугольники Blender или прямые участки карты."""
import math
from collections import defaultdict


class RoadSurface:
    def __init__(self, surfaces, cell_size=10):
        self.cell_size = cell_size
        self.cells = defaultdict(list)
        for source in surfaces:
            surface = dict(source)
            if 'triangle' in surface:
                a, b, c = surface['triangle']
                dx, dz, ex, ez = b[0]-a[0], b[2]-a[2], c[0]-a[0], c[2]-a[2]
                determinant = dx*ez-ex*dz
                if abs(determinant) < 1e-8:
                    continue
                gx = ((b[1]-a[1])*ez-(c[1]-a[1])*dz)/determinant
                gz = (dx*(c[1]-a[1])-ex*(b[1]-a[1]))/determinant
                surface['plane'] = (a, dx, dz, ex, ez, determinant, gx, gz)
                min_x, max_x = min(p[0] for p in (a,b,c)), max(p[0] for p in (a,b,c))
                min_z, max_z = min(p[2] for p in (a,b,c)), max(p[2] for p in (a,b,c))
            else:
                half = surface['width']/2
                min_x, max_x = min(surface['ax'],surface['bx'])-half, max(surface['ax'],surface['bx'])+half
                min_z, max_z = min(surface['az'],surface['bz'])-half, max(surface['az'],surface['bz'])+half
            for x in range(math.floor(min_x/cell_size),math.floor(max_x/cell_size)+1):
                for z in range(math.floor(min_z/cell_size),math.floor(max_z/cell_size)+1):
                    self.cells[x,z].append(surface)

    def contacts(self, x, z, heading, road_id=None):
        candidates = []
        for surface in self.cells.get((math.floor(x/self.cell_size),math.floor(z/self.cell_size)), []):
            if road_id is not None and surface.get('roadId') != road_id:
                continue
            if 'plane' in surface:
                a, dx, dz, ex, ez, determinant, gx, gz = surface['plane']
                u = ((x-a[0])*ez-ex*(z-a[2]))/determinant
                v = (dx*(z-a[2])-(x-a[0])*dz)/determinant
                if min(u,v,1-u-v) < -1e-5:
                    continue
                y = a[1]+gx*(x-a[0])+gz*(z-a[2])
                pitch = -math.atan(gx*math.sin(heading)+gz*math.cos(heading))
                candidates.append((y,pitch))
                continue
            dx, dz = surface['bx']-surface['ax'],surface['bz']-surface['az']
            length2 = dx*dx+dz*dz
            t = ((x-surface['ax'])*dx+(z-surface['az'])*dz)/length2
            if t < -1e-6 or t > 1+1e-6:
                continue
            distance2 = (x-surface['ax']-t*dx)**2+(z-surface['az']-t*dz)**2
            if distance2 > (surface['width']/2)**2:
                continue
            rise = surface['by']-surface['ay']
            y = surface['ay']+t*rise
            pitch = -math.atan(rise*(dx*math.sin(heading)+dz*math.cos(heading))/length2)
            candidates.append((y,pitch))
        return candidates

    def sample(self,x,z,heading,previous_y=0):
        candidates=self.contacts(x,z,heading)
        return min(candidates,key=lambda contact:abs(contact[0]-previous_y)) if candidates else (0.0,0.0)
