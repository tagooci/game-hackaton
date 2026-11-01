"""Экспорт выбранного окружения из Blender: общие прототипы и матрицы экземпляров."""
import bpy
import hashlib
import json
import math
import sys
from pathlib import Path
from mathutils import Matrix, Vector

out = Path(sys.argv[sys.argv.index('--') + 1])
out.mkdir(parents=True, exist_ok=True)
axes = Matrix(((-1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
objects = [obj for collection in bpy.data.collections
           if collection.name.startswith(('CITY 01 ', 'CITY 04 ', 'CITY 05 '))
           for obj in collection.objects if obj.type == 'MESH' and not obj.hide_render]
models = {}
instances = []
colliders = []
images = {}


def bake_colors(mesh):
    # Палитра из textures.rar становится цветами вершин: текстуры не нужны в игре.
    uv = mesh.uv_layers.active
    colors = mesh.color_attributes.new(name='Color', type='FLOAT_COLOR', domain='CORNER')
    for face in mesh.polygons:
        material = mesh.materials[face.material_index] if mesh.materials else None
        texture = next((n.image for n in material.node_tree.nodes
                        if n.type == 'TEX_IMAGE' and n.image and n.image.size[0]), None) if material and material.use_nodes else None
        if texture and texture.name not in images:
            images[texture.name] = list(texture.pixels)
        for index in face.loop_indices:
            if texture and uv:
                u,v = uv.data[index].uv
                width,height = texture.size
                pixel = (min(height-1,max(0,int(v*height)))*width+min(width-1,max(0,int(u*width))))*4
                colors.data[index].color_srgb = images[texture.name][pixel:pixel+4]
            else:
                colors.data[index].color = material.diffuse_color if material else (1,1,1,1)
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    mesh.materials.clear()


templates = {obj.get('source_object'): obj for obj in objects if obj.name.startswith('House_')}
# Повторяем несколько цельных прототипов вместо агрессивного decimate фасадов.
reusable = {'house_06': 'house_09', 'house_10': 'house_09', 'highlivingbuilding_b': 'highlivingbuilding_a'}
for obj in objects:
    source = templates.get(reusable.get(obj.get('source_object')), obj)
    mesh = source.data
    signature = hashlib.sha256(str(([tuple(v.co) for v in mesh.vertices],
        [tuple(p.vertices) for p in mesh.polygons],
        [tuple(u.uv) for u in mesh.uv_layers.active.data] if mesh.uv_layers.active else [],
        [m.name if m else '' for m in mesh.materials])).encode()).hexdigest()[:16]
    asset = 'city-' + signature
    height = max(v.co.z for v in obj.data.vertices)-min(v.co.z for v in obj.data.vertices)
    source_height = max(v.co.z for v in mesh.vertices)-min(v.co.z for v in mesh.vertices)
    local_scale = Matrix.Diagonal((1,1,height/source_height if source_height else 1,1))
    transform = axes @ obj.matrix_world @ local_scale @ axes.inverted()
    points = [axes @ obj.matrix_world @ Vector(v) for v in obj.bound_box]
    bounds = {key: round(fn(p[axis] for p in points),5) for key,fn,axis in
              [('minX',min,0),('maxX',max,0),('minZ',min,2),('maxZ',max,2)]}
    instances.append(dict(id=obj.name, assetId=asset, x=round(-obj.matrix_world.translation.x,5),
        y=round(obj.matrix_world.translation.z,5), z=round(-obj.matrix_world.translation.y,5),
        matrix=[round(transform[row][col],8) for col in range(4) for row in range(4)], bounds=bounds))
    if obj.name.startswith('House_'):
        colliders.append(dict(x=(bounds['minX']+bounds['maxX'])/2,z=(bounds['minZ']+bounds['maxZ'])/2,
            heading=0,halfWidth=(bounds['maxX']-bounds['minX'])/2,halfLength=(bounds['maxZ']-bounds['minZ'])/2,
            minY=min(p.y for p in points),maxY=max(p.y for p in points),objectId=obj.name))
    if asset in models:
        continue
    models[asset] = source.get('source_object',source.name)
    clone = obj.copy()
    clone.data = mesh.copy()
    clone.animation_data_clear()
    bpy.context.collection.objects.link(clone)
    clone.parent = None
    clone.matrix_world = Matrix.Identity(4)
    clone.name = asset
    if obj.name.startswith('ParkBench'):
        clone.data.transform(Matrix.Rotation(-math.pi/2, 4, 'X'))
        bottom = min(v.co.z for v in clone.data.vertices)
        clone.data.transform(Matrix.Translation((0,0,-bottom)))
    bake_colors(clone.data)
    bpy.ops.object.select_all(action='DESELECT')
    clone.select_set(True)
    bpy.context.view_layer.objects.active = clone
    bpy.ops.export_scene.gltf(filepath=str(out/(asset+'.glb')),export_format='GLB',use_selection=True,
        export_yup=True,export_cameras=False,export_lights=False,export_animations=False,
        export_all_vertex_colors=True,export_materials='NONE')
    bpy.data.objects.remove(clone,do_unlink=True)
(out/'scene.json').write_text(json.dumps(dict(objects=instances,models=models,colliders=colliders)))
print('ENVIRONMENT',len(instances),'instances',len(models),'models')
