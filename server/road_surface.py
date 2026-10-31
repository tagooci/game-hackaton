"""Высота дорожного полотна: пространственный индекс поверхностей карты."""
import math
from collections import defaultdict


class RoadSurface:
    def __init__(self, surfaces, cell_size=50):
        self.cell_size = cell_size
        self.cells = defaultdict(list)
        for surface in surfaces:
            half = surface['width'] / 2
            for x in range(math.floor((min(surface['ax'], surface['bx'])-half)/cell_size), math.floor((max(surface['ax'], surface['bx'])+half)/cell_size)+1):
                for z in range(math.floor((min(surface['az'], surface['bz'])-half)/cell_size), math.floor((max(surface['az'], surface['bz'])+half)/cell_size)+1):
                    self.cells[x,z].append(surface)

    def sample(self, x, z, heading, previous_y=0):
        candidates = []
        for surface in self.cells.get((math.floor(x/self.cell_size), math.floor(z/self.cell_size)), []):
            dx, dz = surface['bx']-surface['ax'], surface['bz']-surface['az']
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
            candidates.append((abs(y-previous_y), distance2, y, pitch))
        if not candidates:
            return 0.0, 0.0
        _, _, y, pitch = min(candidates)
        return y, pitch
