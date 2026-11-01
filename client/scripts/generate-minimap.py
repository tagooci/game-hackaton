"""Generate a vector-only overhead map from the actual world meshes.
Requires installed client npm dependencies and Python shapely, cairosvg, Pillow.
Run from repository root: python client/scripts/generate-minimap.py
"""
from pathlib import Path
from collections import defaultdict
import json, subprocess, tempfile, sys
from shapely.geometry import Polygon
from shapely.ops import unary_union

root = Path(__file__).resolve().parents[1]
nav = json.loads((root/'public/content/world/navigation.json').read_text())
manifest = json.loads((root/'public/content/world/manifest.json').read_text())
points = [p for s in nav['surfaces'] for p in s['triangle']]
min_x,max_x=min(p[0] for p in points),max(p[0] for p in points)
min_z,max_z=min(p[2] for p in points),max(p[2] for p in points)
size=max(max_x-min_x,max_z-min_z)+16
cx,cz=(min_x+max_x)/2,(min_z+max_z)/2
bounds=dict(minX=cx-size/2,maxX=cx+size/2,minZ=cz-size/2,maxZ=cz+size/2)
scale=1000/size
if len(sys.argv)>1:
    triangles=json.loads(Path(sys.argv[1]).read_text())
else:
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'geometry.json'
        subprocess.run(['node',str(root/'scripts/export-minimap-geometry.mjs'),str(path)],check=True)
        triangles=json.loads(path.read_text())
groups=defaultdict(list)
for t in triangles:
    polygon=Polygon(t['p'])
    if polygon.is_valid and polygon.area>.001:
        color='#'+''.join(f'{min(255,round(int(t["color"][i:i+2],16)/12)*12):02x}' for i in (1,3,5))
        groups[(round(t['y'],1),color)].append(polygon)

def paths(shape):
    if shape.is_empty or shape.area < .04:return ''
    if shape.geom_type=='Polygon':
        result=[]
        for ring in [shape.exterior,*shape.interiors]:
            pts=[((x-bounds['minX'])*scale,(bounds['maxZ']-z)*scale) for x,z in ring.coords]
            result.append('M'+'L'.join(f'{x:.1f},{y:.1f}' for x,y in pts)+'Z')
        return ''.join(result)
    return ''.join(paths(p) for p in shape.geoms) if hasattr(shape,'geoms') else ''

layers=[]
from shapely.geometry import GeometryCollection
by_height=defaultdict(list)
for (height,color),polygons in groups.items():
    shape=unary_union([p.buffer(.001,join_style=2) for p in polygons]).simplify(.12,preserve_topology=True)
    by_height[height].append((color,shape))
covered=GeometryCollection()
# Work front to back: discard faces hidden by roofs, trees and upper roads.
for height,entries in sorted(by_height.items(),reverse=True):
    visible_layers=[]
    for color,shape in entries:
        visible=shape.difference(covered).simplify(.12,preserve_topology=True)
        if visible.area < .003:continue
        d=paths(visible)
        if d:visible_layers.append(f'<path fill="{color}" stroke="{color}" stroke-width="0.6" d="{d}"/>')
    covered=unary_union([covered,*[shape for _,shape in entries]])
    layers.insert(0,'\n'.join(visible_layers))
svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">\n<title>Вся трасса с домами и дорожной разметкой</title>\n<defs><clipPath id="bounds"><path d="M0 0H1000V1000H0Z"/></clipPath></defs>\n<g fill-rule="evenodd" stroke-linejoin="round" clip-path="url(#bounds)">\n'+'\n'.join(layers)+'\n</g></svg>\n'
out=root/'src/assets/minimap';out.mkdir(parents=True,exist_ok=True)
(out/'track.svg').write_text(svg)
(out/'map.json').write_text(json.dumps(dict(bounds=bounds,worldId=manifest['worldId'],contentVersion=manifest['contentVersion'],roadCount=len(nav['sourceRoads'])),indent=2)+'\n')
print(f'Generated vector map: {len(layers)} layers, {len(svg):,} bytes; no raster images or background.')

# Keep SVG as the editable source; ship a pre-rasterized lossless bitmap to the HUD.
import io, cairosvg
from PIL import Image
png=cairosvg.svg2png(bytestring=svg.encode(),output_width=560,output_height=560)
Image.open(io.BytesIO(png)).save(out/'track.webp',format='WEBP',lossless=True,method=6)
print(f"Runtime bitmap: {(out/'track.webp').stat().st_size:,} bytes")
