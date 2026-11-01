"""Выделяет перекрёсток и его коллизии из опубликованной карты без копирования моделей."""
from pathlib import Path
import json,gzip,hashlib
root=Path(__file__).resolve().parents[1]/'public'
m=json.loads((root/'content/world/manifest.json').read_text()); n=json.loads((root/'content/world/navigation.json').read_text())
ids={'Compact_001_road-straight','Compact_005_road-straight','Compact_002_road-straight','Compact_003_road-intersection-path','Compact_004_road-straight','S01 - STOCK CURVED ASCENT'}
objects=[]
for c in m['chunks']:
 r=next(r for r in m['resources'] if r['id']==c['resourceId'])
 d=json.loads(gzip.decompress((root/r['url'].lstrip('/')).read_bytes()))
 objects.extend(o for o in d['objects'] if o['id'] in ids)
assert len(objects)==6
out=root/'content/scenarios/left-turn';out.mkdir(parents=True,exist_ok=True)
def resource(name,data):
 b=gzip.compress(json.dumps(data,separators=(',',':')).encode(),mtime=0);(out/name).write_bytes(b)
 return dict(id='scenario-'+name,kind='data',url='/content/scenarios/left-turn/'+name,bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),encoding='gzip')
sign_resources=json.loads((Path(__file__).resolve().parents[2]/'blender/scenario-signs/resources.json').read_text())
objects.extend([
 dict(id='priority-A',assetId='sign-priority',x=55.6,y=.2,z=28,heading=0,scale=1),
 dict(id='priority-B',assetId='sign-priority',x=64.4,y=.2,z=12,heading=3.141592653589793,scale=1),
 dict(id='yield-C',assetId='sign-yield',x=52,y=.2,z=15.6,heading=-1.5707963267948966,scale=1),
])
chunk=resource('junction.json.bin',dict(objects=objects,signs=[]))
overview=resource('overview.json.bin',{})
assets={o['assetId'] for o in objects}
s=dict(m);s.update(worldId=m['worldId']+':left-turn',chunks=[dict(id='junction',resourceId=chunk['id'],assetIds=sorted(assets),bounds=dict(minX=30,maxX=65,minZ=-5,maxZ=45))],resources=[r for r in m['resources'] if r['id'] in assets]+sign_resources+[chunk,overview],overviewResourceId=overview['id'])
(out/'manifest.json').write_text(json.dumps(s,separators=(',',':')))
nav={k:[v for v in n[k] if v.get('roadId',v.get('objectId')) in ids] for k in ('surfaces','ceilings','colliders')}
(out/'navigation.json').write_text(json.dumps(nav,separators=(',',':')))
