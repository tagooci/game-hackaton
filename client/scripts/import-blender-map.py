"""Импорт Blender-карты в существующие чанки, GLB и серверные поверхности."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'public/content'
def encode(value):return json.dumps(value,separators=(',',':')).encode()
def digest(data):return hashlib.sha256(data).hexdigest()
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scene',type=Path,required=True)
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--blender',required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('road_pack',Path(__file__).with_name('prepare-road-assets.py'))
    packer=importlib.util.module_from_spec(spec);spec.loader.exec_module(packer)
    class Files:
        def read(self,path):return (args.assets/path).read_bytes()
    resources=[];catalog={}
    for path in (ROOT/'assets/imported').glob('map-*.glb*'):path.unlink()
    def publish(id,path,data,kind='data',**extra):
        target=ROOT/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        resource=dict(id=id,url='/content/'+path,kind=kind,bytes=len(data),sha256=digest(data),**extra)
        resources.append(resource);return resource
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([args.blender,'-b',str(args.scene),'--python-exit-code','1','--python',str(Path(__file__).with_name('export-blender-map.py')),'--',tmp],check=True,stdout=subprocess.DEVNULL)
        scene=json.loads((Path(tmp)/'scene.json').read_text())
        for asset,label in scene['models'].items():
            data=packer.pack((Path(tmp)/(asset+'.glb')).read_bytes(),Files(),'.')
            catalog[asset]=publish(asset,'assets/imported/'+asset+'.glb.bin',gzip.compress(data,mtime=0),'model',encoding='gzip',label=label)
    # Порты из авторской карты уже проверены в Blender. Сохраняем разделение уровней моста.
    nodes=[];ports={};links={}
    for road in scene['roads']:
        for group in sorted({p['group'] for p in road['ports']}):
            ps=[p for p in road['ports'] if p['group']==group];id=road['object']+':'+group
            node=dict(id=id,roadId=road['object'],x=sum(-p['position'][0] for p in ps)/len(ps),
                      y=sum(p['position'][2] for p in ps)/len(ps),z=sum(-p['position'][1] for p in ps)/len(ps),neighbors=[])
            nodes.append(node);links[id]=set()
            for p in ps:
                key=tuple(round(v,3) for v in p['position']);ports.setdefault(key,[]).append((id,p))
    for key,pairs in ports.items():
        if len(pairs)!=2:raise ValueError(f'Unmatched port: {key}')
        (a,p),(b,q)=pairs
        if p['direction']!=[-v for v in q['direction']]:raise ValueError(f'Invalid port directions: {key}')
        links[a].add(b);links[b].add(a)
    for node in nodes:node['neighbors']=sorted(links[node['id']])
    seen=set();pending=[nodes[0]['id']]
    while pending:
        id=pending.pop()
        if id in seen:continue
        seen.add(id);pending.extend(links[id]-seen)
    if len(seen)!=len(nodes):raise ValueError('Disconnected road map')
    registry={n['id']:n for n in nodes};lanes=[]
    for n in nodes:
        for next_id in n['neighbors']:
            q=registry[next_id]
            lanes.append(dict(id=n['id']+'>'+next_id,roadId=n['roadId'],width=3,centerline=[dict(x=n['x'],y=n['y'],z=n['z']),dict(x=q['x'],y=q['y'],z=q['z'])],
                              nextLaneIds=[next_id+'>'+end for end in q['neighbors'] if end!=n['id']]))
    nav=dict(nodes=nodes,lanes=lanes,surfaces=scene['surfaces'],features=[],sourceRoads=scene['roads'],
             validation=dict(connected=True,totalRoads=len(nodes),reachableRoads=len(seen),deadEndPorts=0))
    overview=dict(nodes=[{k:v for k,v in n.items() if k!='neighbors'} for n in nodes if len(n['neighbors'])>2],features=[],edges=[])
    publish('road-navigation','world/navigation.json',encode(nav))
    publish('road-overview','world/overview.json',encode(overview))
    chunks={};size=20
    for obj in scene['objects']:
        cx,cz=math.floor(obj['x']/size),math.floor(obj['z']/size);id=f'road-{cx}-{cz}'
        if id not in chunks:chunks[id]=dict(id=id,bounds=dict(minX=cx*size,maxX=(cx+1)*size,minZ=cz*size,maxZ=(cz+1)*size),objects=[],signs=[])
        chunk=chunks[id]
        for name,value in obj['bounds'].items():chunk['bounds'][name]=(min if name.startswith('min') else max)(chunk['bounds'][name],value)
        chunk['objects'].append(obj)
    for path in (ROOT/'world/chunks').glob('road-*.json*'):path.unlink()
    descriptors=[]
    for id,chunk in chunks.items():
        publish(id,'world/chunks/'+id+'.json.bin',gzip.compress(encode(chunk),mtime=0),encoding='gzip')
        descriptors.append(dict(id=id,bounds=chunk['bounds'],resourceId=id,assetIds=sorted({o['assetId'] for o in chunk['objects']})))
    unique={r['sha256']:r['bytes'] for r in resources};world_bytes=sum(unique.values())
    first=next(r for r in scene['roads'] if r['asset']=='road-straight' and r['position'][2]==0)
    a,b=first['ports'];dx=-(b['position'][0]-a['position'][0]);dz=-(b['position'][1]-a['position'][1]);length=math.hypot(dx,dz)
    spawn=dict(x=-first['position'][0]+dz/length*1.5,z=-first['position'][1]-dx/length*1.5,heading=math.atan2(dx,dz))
    bounds={key:(min if key.startswith('min') else max)(c['bounds'][key] for c in descriptors) for key in ['minX','maxX','minZ','maxZ']}
    manifest=dict(worldId='compact-reference-'+digest(encode(scene['roads']))[:8],contentVersion=digest(encode(resources))[:16],
                  accounting='unique_resource_bytes',worldBytes=world_bytes,cacheBudgetBytes=world_bytes//10,tileSize=10,chunkSize=size,
                  streamRadius=65,streamStep=2.5,bounds=bounds,spawn=spawn,groundColor='#35353f',resources=resources,chunks=descriptors,
                  overviewResourceId='road-overview',navigationResourceId='road-navigation',stats=dict(roadTiles=len(scene['roads']),chunks=len(chunks),objects=len(scene['objects']),models=len(catalog)))
    (ROOT/'world/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    previous=json.loads((ROOT/'asset-catalog.json').read_text())
    previous.update(catalog)
    (ROOT/'asset-catalog.json').write_text(json.dumps(previous,indent=2)+'\n')
    license_text=(args.assets.parent.parent/'License.txt').read_text()
    (ROOT/'assets/imported/License.txt').write_text('\n'.join(line.rstrip() for line in license_text.splitlines())+'\n')
    print(json.dumps(dict(worldBytes=world_bytes,budget=manifest['cacheBudgetBytes'],spawn=spawn,**manifest['stats']),indent=2))

if __name__=='__main__':main()
