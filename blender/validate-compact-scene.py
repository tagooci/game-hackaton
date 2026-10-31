import bpy,json,math
from mathutils import Vector
scene=bpy.context.scene
records=json.loads(scene['compact_records'])
def ports_for(ob):
 me=ob.data;uv=me.uv_layers.active;result=[]
 for axis in [0,1]:
  for side in [-1,1]:
   bound=(min if side<0 else max)(v.co[axis] for v in me.vertices)
   pts=[]
   for poly in me.polygons:
    u=uv.data[poly.loop_start].uv
    if abs(u.x-.28125)>.004:continue
    for vi in poly.vertices:
     v=me.vertices[vi].co
     if abs(v[axis]-bound)<.0001:pts.append(v.copy())
   if not pts:continue
   vals=[sum(v[i] for v in pts)/len(pts) for i in range(3)]
   vals[axis]=bound;vals[1-axis]=(min(v[1-axis] for v in pts)+max(v[1-axis] for v in pts))/2
   p=ob.matrix_world@Vector(vals)
   d=ob.rotation_euler.to_matrix()@Vector((side if axis==0 else 0,side if axis==1 else 0,0))
   # exact interval endpoints used for seam validation
   lo=Vector(vals);hi=Vector(vals);lo[1-axis]=min(v[1-axis] for v in pts);hi[1-axis]=max(v[1-axis] for v in pts)
   result.append({'position':list(p),'direction':[round(d.x),round(d.y)],'endpoints':[list(ob.matrix_world@lo),list(ob.matrix_world@hi)],'group':'upper' if ob.get('source_asset')=='road-bridge' and vals[2]>.25 else 'lower' if ob.get('source_asset')=='road-bridge' else 'all'})
 return result
bpy.context.view_layer.update()
for r in records:r['ports']=ports_for(bpy.data.objects[r['object']])
scene['compact_records']=json.dumps(records)
import bpy,json,math
from mathutils import Vector
scene=bpy.context.scene;rs=json.loads(scene['compact_records']);allports=[(i,j,p) for i,r in enumerate(rs) for j,p in enumerate(r['ports'])]
unmatched=[];matches=[];adj={};errors=[]
for i,j,p in allports:
 candidates=[(k,l,q) for k,l,q in allports if k!=i and sum((p['position'][a]-q['position'][a])**2 for a in range(3))<.00001 and p['direction']==[-d for d in q['direction']]]
 if len(candidates)!=1:unmatched.append({'object':rs[i]['object'],'port':p,'candidates':len(candidates)});continue
 k,l,q=candidates[0];matches.append((i,j,k,l))
 # A native bridge has separate upper/lower internal connectivity.
 a=(i,p['group']);b=(k,q['group']);adj.setdefault(a,set()).add(b);adj.setdefault(b,set()).add(a)
 ep=[Vector(v) for v in p['endpoints']];eq=[Vector(v) for v in q['endpoints']]
 gap=min(max((ep[0]-eq[0]).length,(ep[1]-eq[1]).length),max((ep[0]-eq[1]).length,(ep[1]-eq[0]).length))
 if gap>.002:errors.append({'a':rs[i]['object'],'b':rs[k]['object'],'gap':gap})
seen=set();pending=[next(iter(adj))]
while pending:
 k=pending.pop()
 if k in seen:continue
 seen.add(k);pending.extend(adj[k]-seen)
horizontal=[]
for r in rs:
 ob=bpy.data.objects[r['object']]
 if 'slant' not in r['asset'] and r['asset']!='road-bridge':
  zs=[p['position'][2] for p in r['ports']]
  if max(zs)-min(zs)>.0001:horizontal.append(r['object'])
report={'modules':len(rs),'directed_connections':len(matches),'connected':len(seen)==len(adj),'dead_end_ports':len(unmatched),'seam_errors':errors,'nonhorizontal_flat_modules':horizontal,'unmatched':unmatched}
scene['compact_validation']=json.dumps(report)
print(json.dumps({**report,'unmatched':unmatched[:12]},indent=2))

import bpy,json,math
from mathutils import Vector
scene=bpy.context.scene;rs=json.loads(scene['compact_records']);ps=[(i,j,p) for i,r in enumerate(rs) for j,p in enumerate(r['ports'])]
def curbs(r,p):
 ob=bpy.data.objects[r['object']];me=ob.data;uv=me.uv_layers.active;pts=[];direction=Vector((*p['direction'],0));center=Vector(p['position']);tangent=Vector((-direction.y,direction.x,0))
 for poly in me.polygons:
  u=uv.data[poly.loop_start].uv
  if poly.normal.z<.1:continue
  for vi in poly.vertices:
   v=ob.matrix_world@me.vertices[vi].co
   if abs((v-center).dot(direction))<.001 and .075<v.z-center.z<.125 and abs((v-center).dot(tangent))>3.9:pts.append(v)
 if not pts:return None
 left=[v for v in pts if (v-center).dot(tangent)<-3.5];right=[v for v in pts if (v-center).dot(tangent)>3.5]
 if not left or not right:return None
 return (min((v-center).dot(tangent) for v in pts),max((v-center).dot(tangent) for v in pts),min(v.z for v in pts),max(v.z for v in pts))
missing=[];gaps=[];pairs=0
for i,j,p in ps:
 cs=[(k,l,q) for k,l,q in ps if k!=i and (Vector(p['position'])-Vector(q['position'])).length<.002 and p['direction']==[-d for d in q['direction']]]
 if len(cs)!=1:continue
 k,l,q=cs[0];a=curbs(rs[i],p);b=curbs(rs[k],q);pairs+=1
 if a is None or b is None:missing.append([rs[i]['object'],rs[k]['object'],a,b]);continue
 # Neighbor normal is reversed; cross-axis interval has the opposite signs.
 bb=(-b[1],-b[0],b[2],b[3]);gap=max(abs(x-y) for x,y in zip(a,bb))
 if gap>.005:gaps.append([rs[i]['object'],rs[k]['object'],gap,a,b])
# Longest run of plain straight modules. A ramp/turn/junction breaks the run.
straight={i for i,r in enumerate(rs) if r['asset']=='road-straight'};edges={i:set() for i in straight}
for i,j,p in ps:
 if i not in straight:continue
 for k,l,q in ps:
  if k in straight and k!=i and (Vector(p['position'])-Vector(q['position'])).length<.002:edges[i].add(k)
seen=set();runs=[]
for i in straight:
 if i in seen:continue
 todo=[i];n=0
 while todo:
  k=todo.pop()
  if k in seen:continue
  seen.add(k);n+=1;todo.extend(edges[k]-seen)
 runs.append(n)
# Verify lamp head points toward its road target and base is on the curb.
lamps=json.loads(scene['compact_lamps']);lamp_errors=[]
for l in lamps:
 ob=bpy.data.objects[l['object']];d=ob.rotation_euler.to_matrix()@Vector((0,1,0));t=Vector(l['target'])-Vector(l['pole']);t.z=0;t.normalize()
 if d.dot(t)<.999:lamp_errors.append(l['object'])
report=json.loads(scene['compact_validation'])
report.update({'curb_connections_checked':pairs,'missing_curbs':missing,'curb_seam_errors':gaps,'maximum_plain_straight_run_tiles':max(runs),'maximum_plain_straight_run_m':max(runs)*10,'street_lamps':len(lamps),'lamps_facing_away_from_road':lamp_errors,'original_road_geometry':all(bpy.data.objects[r['object']].data==bpy.data.objects['CMP_SRC_'+r['asset']].data for r in rs)})
scene['compact_validation']=json.dumps(report)
print(json.dumps({**report,'missing_curbs':missing[:5],'curb_seam_errors':gaps[:5]},indent=2))
