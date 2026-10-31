"""Экспорт экземпляров и точных поверхностей из Blender, без изменения .blend."""
import bpy
import hashlib
import json
import sys
from pathlib import Path
from mathutils import Matrix

out = Path(sys.argv[sys.argv.index('--')+1]);out.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
records = json.loads(scene['compact_records'])
roads = {record['object'] for record in records}
objects = [obj for collection in bpy.data.collections if collection.name.startswith(('C01 ', 'C02 ', 'C03 ', 'C04 '))
           for obj in collection.objects if obj.type == 'MESH' and not obj.hide_render]
objects = list({obj.name:obj for obj in objects}.values())
# Blender XYZ -> Babylon (-X,Z,-Y); это также стандартное преобразование экспортера glTF + loader Babylon.
axes = Matrix(((-1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
def point(vector):return [round(v,5) for v in (axes @ vector)]

instances=[];surfaces=[];models={}
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
    if obj.name in roads:
        normal_matrix=obj.matrix_world.to_3x3().inverted().transposed()
        for triangle in mesh.loop_triangles:
            if (normal_matrix @ triangle.normal).normalized().z <= .1:continue
            pts=[point(obj.matrix_world @ mesh.vertices[i].co) for i in triangle.vertices]
            if abs((pts[1][0]-pts[0][0])*(pts[2][2]-pts[0][2])-(pts[2][0]-pts[0][0])*(pts[1][2]-pts[0][2])) < .000001:continue
            surfaces.append({'triangle':pts,'roadId':obj.name})
    if asset in models:continue
    models[asset]=obj.get('source_asset') or obj.name
    clone=obj.copy();clone.data=mesh.copy();clone.animation_data_clear()
    bpy.context.collection.objects.link(clone);clone.parent=None;clone.matrix_world=Matrix.Identity(4);clone.name=asset
    bpy.ops.object.select_all(action='DESELECT');clone.select_set(True);bpy.context.view_layer.objects.active=clone
    bpy.ops.export_scene.gltf(filepath=str(out/(asset+'.glb')),export_format='GLB',use_selection=True,
                              export_yup=True,export_cameras=False,export_lights=False,export_animations=False)
    bpy.data.objects.remove(clone,do_unlink=True)
(out/'scene.json').write_text(json.dumps({'objects':instances,'surfaces':surfaces,'roads':records,'models':models}))
print('EXPORTED',len(instances),'instances',len(models),'models',len(surfaces),'surface triangles')
