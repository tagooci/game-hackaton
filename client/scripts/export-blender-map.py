"""Экспорт экземпляров и точных поверхностей из Blender, без изменения .blend."""
import bpy
import hashlib
import json
import math
import sys
from pathlib import Path
from mathutils import Matrix

out = Path(sys.argv[sys.argv.index('--')+1]);out.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
records = json.loads(scene['compact_records'])
road_records = {record['object']:record for record in records}
roads = set(road_records)
objects = [obj for collection in bpy.data.collections if collection.name.startswith(('C01 ', 'C02 ', 'C03 ', 'C04 '))
           for obj in collection.objects if obj.type == 'MESH' and not obj.hide_render]
objects = list({obj.name:obj for obj in objects}.values())
# Blender XYZ -> Babylon (-X,Z,-Y); это также стандартное преобразование экспортера glTF + loader Babylon.
axes = Matrix(((-1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
def point(vector):return [round(v,5) for v in (axes @ vector)]

def raised_curbs(box,pts,ports):
    # Бордюр тонкий по вертикали даже на уклоне; опоры высотой несколько метров сюда не входят.
    thickness=max((abs(a[1]-b[1]) for a in pts for b in pts
                   if math.hypot(a[0]-b[0],a[2]-b[2])<.0001),default=0)
    if not .025 <= thickness <= .4:return []
    forward=(math.sin(box['heading']),math.cos(box['heading']))
    center=box['x']*forward[0]+box['z']*forward[1]
    spans=[(center-box['halfLength'],center+box['halfLength'])]
    for port in ports:
        px,pz=-port['position'][0],-port['position'][1]
        nx,nz=-port['direction'][0],-port['direction'][1]
        if not box['minY']-.05 <= port['position'][2] <= box['maxY']+.05:continue
        if any(abs((p[0]-px)*nx+(p[2]-pz)*nz)>.03 for p in pts):continue
        ends=[-p[0]*forward[0]-p[1]*forward[1] for p in port['endpoints']]
        low,high=min(ends),max(ends)
        # Проём между модулями вырезается из высокого бокса, иначе перекроется сама дорога.
        spans=[part for a,b in spans for part in
               ([(a,b)] if b<=low or a>=high else [(a,min(b,low)),(max(a,high),b)]) if part[1]-part[0]>.02]
    result=[]
    for a,b in spans:
        shift=(a+b)/2-center
        result.append({**box,'x':round(box['x']+forward[0]*shift,5),
                       'z':round(box['z']+forward[1]*shift,5),'halfLength':round((b-a)/2,5),
                       'maxY':round(box['maxY']+2.5,5),'kind':'curb'})
    return result

instances=[];surfaces=[];ceilings=[];boxes=[];models={}
for obj in objects:
    mesh=obj.data
    mesh.calc_loop_triangles()
    uv=mesh.uv_layers.active
    signature=hashlib.sha256()
    signature.update(str(([tuple(v.co) for v in mesh.vertices],[tuple(p.vertices) for p in mesh.polygons],
                          [tuple(u.uv) for u in uv.data] if uv else [],[m.name if m else '' for m in mesh.materials])).encode())
    asset='map-'+signature.hexdigest()[:16]
    transform=axes @ obj.matrix_world @ axes.inverted()
    entry={'id':obj.name,'assetId':asset,'x':round(-obj.matrix_world.translation.x,5),
           'y':round(obj.matrix_world.translation.z,5),'z':round(-obj.matrix_world.translation.y,5),
           'matrix':[round(transform[row][col],8) for col in range(4) for row in range(4)]}
    # Части с центром вне геометрии привязываются к своему реальному bbox.
    corners=[point(obj.matrix_world @ __import__('mathutils').Vector(corner)) for corner in obj.bound_box]
    entry['bounds']={key:round(fn(p[axis] for p in corners),5) for key,fn,axis in
                     [('minX',min,0),('maxX',max,0),('minZ',min,2),('maxZ',max,2)]}
    instances.append(entry)
    normal_matrix=obj.matrix_world.to_3x3().inverted().transposed()
    if obj.name in roads or any(collection.name.startswith('C02 ') for collection in obj.users_collection):
        for triangle in mesh.loop_triangles:
            normal=(normal_matrix @ triangle.normal).normalized().z
            if abs(normal)<=.1:continue
            pts=[point(obj.matrix_world @ mesh.vertices[i].co) for i in triangle.vertices]
            if abs((pts[1][0]-pts[0][0])*(pts[2][2]-pts[0][2])-(pts[2][0]-pts[0][0])*(pts[1][2]-pts[0][2])) < .000001:continue
            target=surfaces if normal>.1 and obj.name in roads else ceilings if normal<-.1 else None
            if target is not None:target.append({'triangle':pts,'roadId':obj.name})
    # Небольшие боксы по вертикальным граням сохраняют проходы под мостами,
    # вместо одного большого bbox, который закрыл бы весь мостовой модуль.
    for face in mesh.polygons:
        if abs((normal_matrix @ face.normal).normalized().z)>.5:continue
        pts=[point(obj.matrix_world @ mesh.vertices[i].co) for i in face.vertices]
        bottom,top=min(p[1] for p in pts),max(p[1] for p in pts)
        if top-bottom<.025:continue
        a,b=max(((a,b) for a in pts for b in pts),key=lambda pair:(pair[0][0]-pair[1][0])**2+(pair[0][2]-pair[1][2])**2)
        heading=math.atan2(b[0]-a[0],b[2]-a[2]);right=(math.cos(heading),-math.sin(heading));forward=(math.sin(heading),math.cos(heading))
        lateral=[p[0]*right[0]+p[2]*right[1] for p in pts];along=[p[0]*forward[0]+p[2]*forward[1] for p in pts]
        width,length=max(lateral)-min(lateral),max(along)-min(along)
        if length<.04:continue
        side=(min(lateral)+max(lateral))/2;front=(min(along)+max(along))/2
        box=dict(x=side*right[0]+front*forward[0],z=side*right[1]+front*forward[1],heading=heading,
                 halfWidth=max(.02,width/2),halfLength=length/2,minY=bottom,maxY=top,objectId=obj.name)
        box={k:round(v,5) if isinstance(v,float) else v for k,v in box.items()}
        boxes.append(box)
        if obj.name in road_records:boxes.extend(raised_curbs(box,pts,road_records[obj.name]['ports']))
    if asset in models:continue
    models[asset]=obj.get('source_asset') or obj.name
    clone=obj.copy();clone.data=mesh.copy();clone.animation_data_clear()
    bpy.context.collection.objects.link(clone);clone.parent=None;clone.matrix_world=Matrix.Identity(4);clone.name=asset
    bpy.ops.object.select_all(action='DESELECT');clone.select_set(True);bpy.context.view_layer.objects.active=clone
    bpy.ops.export_scene.gltf(filepath=str(out/(asset+'.glb')),export_format='GLB',use_selection=True,
                              export_yup=True,export_cameras=False,export_lights=False,export_animations=False)
    bpy.data.objects.remove(clone,do_unlink=True)
(out/'scene.json').write_text(json.dumps({'objects':instances,'surfaces':surfaces,'ceilings':ceilings,'colliders':boxes,'roads':records,'models':models}))
print('EXPORTED',len(instances),'instances',len(models),'models',len(surfaces),'surface triangles')
