import bpy,math
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parents[2]
for name,target in [('PoleWithSignDiamond60','priority'),('PoleWithSignTriangleDown60','yield')]:
 bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
 bpy.ops.wm.obj_import(filepath=str(root/'blender/scenario-signs'/name/(name+'.obj')))
 objects=[o for o in bpy.context.scene.objects if o.type=='MESH']
 points=[o.matrix_world@Vector(v) for o in objects for v in o.bound_box]
 low=Vector(tuple(min(p[i] for p in points) for i in range(3)));high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
 scale=2.8/(high.z-low.z);offset=Vector(((low.x+high.x)/2,(low.y+high.y)/2,low.z))
 for o in objects:
  o.location=(o.location-offset)*scale;o.scale*=scale
  for mat in o.data.materials:
   if mat and mat.use_nodes:
    bs=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if bs:bs.inputs['Metallic'].default_value=0;bs.inputs['Roughness'].default_value=.9
 bpy.ops.export_scene.gltf(filepath=str(root/'blender/scenario-signs'/(target+'.glb')),export_format='GLB')
 print(target,'size',tuple(high-low))

# Сохраняем автономные GLB в общем каталоге моделей и описываем их для манифеста.
import gzip, hashlib, json
resources=[]
for name in ('priority','yield'):
    data=gzip.compress((root/'blender/scenario-signs'/(name+'.glb')).read_bytes(),mtime=0)
    path=root/'client/public/content/assets/imported'/('sign-'+name+'.glb.bin')
    path.write_bytes(data)
    resources.append(dict(id='sign-'+name,kind='model',url='/content/assets/imported/'+path.name,
                          bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),encoding='gzip'))
(root/'blender/scenario-signs/resources.json').write_text(json.dumps(resources,indent=2)+'\n')
