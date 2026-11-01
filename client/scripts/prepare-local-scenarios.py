"""Export scenarios 2 and 4 from published world tiles; original world is unchanged."""
from pathlib import Path
import gzip, hashlib, json, math
ROOT = Path(__file__).resolve().parents[1] / 'public'
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def line(a,b,n=20): return [[a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n] for i in range(n+1)]
def curve(points,n=30):
    a,b,c,d=points
    return [[(1-t)**3*a[j]+3*(1-t)**2*t*b[j]+3*(1-t)*t*t*c[j]+t**3*d[j] for j in (0,1)] for t in [i/n for i in range(n+1)]]
def arc(start,end,n=65): return [[8*math.cos(t),-40+8*math.sin(t)] for t in [start+(end-start)*i/n for i in range(n+1)]]
def pose(x,z,h): return dict(x=x,z=z,heading=h)
def role(id,description,spawn,finish,route):return dict(id=id,description=description,spawn=spawn,finish=finish,route=route)
m=read(ROOT/'content/world/manifest.json'); nav=read(ROOT/'content/world/navigation.json')
objects=[]
for chunk in m['chunks']:
    r=next(r for r in m['resources'] if r['id']==chunk['resourceId'])
    objects += json.loads(gzip.decompress((ROOT/r['url'].lstrip('/')).read_bytes()))['objects']
# Deduplicate objects that appear in neighbouring chunks.
objects=list({o['id']:o for o in objects}.values())
equal=dict(id='equal-priority',number=2,title='Равнозначный перекрёсток',kind='equal',center=[30,-10],requiredPlayers=3,timeLimitSeconds=90,
    trigger=dict(minX=15,maxX=45,minZ=-25,maxZ=5,minY=-.2,maxY=2.5),
    roleIds=['south-left','east-straight','north-straight'],
    roles=[role('south-left','Поверните налево и остановитесь у своей арки.',pose(31.5,-23,0),pose(16,-8.5,-math.pi/2),line((31.5,-23),(31.5,-16.5))+curve([(31.5,-16.5),(31.5,-12),(28,-8.5),(23.5,-8.5)])+line((23.5,-8.5),(16,-8.5))),
           role('east-straight','Проедьте прямо на запад и остановитесь у своей арки.',pose(43,-8.5,-math.pi/2),pose(20,-8.5,-math.pi/2),line((43,-8.5),(20,-8.5))),
           role('north-straight','Проедьте прямо на юг и остановитесь у своей арки.',pose(28.5,3,math.pi),pose(28.5,-23,math.pi),line((28.5,3),(28.5,-23)))],
    yieldsTo={'south-left':['east-straight','north-straight'],'east-straight':['north-straight']},signs=[])
# Ring entry/exit curves follow the original 30 m roundabout tile.
def rotate(points,angle):
    return [[x*math.cos(angle)-(z+40)*math.sin(angle),-40+x*math.sin(angle)+(z+40)*math.cos(angle)] for x,z in points]
entry=curve([(1.5,-53),(1.5,-51),(3.4062259269,-47.5098352136),(4.9728797462,-46.2666152770)])
exit=curve([(4.9728797462,-33.7333847230),(3.4062259269,-32.4901647864),(1.5,-28),(1.5,-26)])
a=line((1.5,-61),(1.5,-53))+entry+arc(-.9,.9+math.pi/2)+rotate(exit,math.pi/2)+line((-14,-38.5),(-23,-38.5))
b=line((-23,-41.5),(-13,-41.5))+rotate(entry,-math.pi/2)+arc(-.9-math.pi/2,.9-math.pi/2)+rotate(exit,-math.pi/2)+line((14,-41.5),(23,-41.5))
c=arc(0,.9)+exit+line((1.5,-26),(1.5,-22))
roundabout=dict(id='roundabout',number=4,title='Круговое движение',kind='roundabout',center=[0,-40],requiredPlayers=3,timeLimitSeconds=90,
    trigger=dict(minX=-25,maxX=25,minZ=-65,maxZ=-20,minY=-.2,maxY=2.5),roleIds=['south-third','west-second','ring-north'],
    roles=[role('south-third','Въедьте на круг и покиньте его через третий выезд — на запад.',pose(1.5,-61,0),pose(-23,-38.5,-math.pi/2),a),
           role('west-second','Въедьте на круг и покиньте его через второй выезд — на восток.',pose(-23,-41.5,math.pi/2),pose(23,-41.5,math.pi/2),b),
           role('ring-north','Продолжите движение по кругу и покиньте его через ближайший северный выезд.',pose(8,-40,0),pose(1.5,-22,0),c)],
    signs=[dict(x=-3.8,z=-55,heading=0),dict(x=-15,z=-36.2,heading=math.pi/2),dict(x=3.8,z=-25,heading=math.pi),dict(x=15,z=-43.8,heading=-math.pi/2)])
for config,ids in [(equal,{'Compact_027_road-crossroad-path','Compact_025_road-straight','Compact_026_road-straight','Compact_028_road-straight','Compact_036_road-straight','Compact_041_road-straight','Compact_018_road-straight'}),
                   (roundabout,{'Compact_097_road-roundabout','Compact_061_road-straight','Compact_037_road-intersection-path','Compact_050_road-straight','S05 - STOCK TWO LEVEL BRIDGE'})]:
    out=ROOT/'content/scenarios'/config['id'];out.mkdir(parents=True,exist_ok=True)
    selected=[o for o in objects if o['id'] in ids]
    assert len(selected)==len(ids),(config['id'],ids-{o['id'] for o in selected})
    extra=[]
    if config['signs']:
        signs=read(ROOT.parents[1]/'blender/scenario-signs/resources.json')
        extra=[r for r in signs if r['id']=='sign-yield']
        selected += [dict(id=f'yield-{i}',assetId='sign-yield',x=s['x'],y=.1,z=s['z'],heading=s['heading'],scale=1) for i,s in enumerate(config['signs'])]
    def resource(name,data):
        data=gzip.compress(json.dumps(data,separators=(',',':')).encode(),mtime=0);(out/name).write_bytes(data)
        return dict(id=config['id']+'-'+name,kind='data',url='/content/scenarios/'+config['id']+'/'+name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),encoding='gzip')
    chunk=resource('junction.json.bin',dict(objects=selected,signs=[]));overview=resource('overview.json.bin',{})
    assets={o['assetId'] for o in selected}
    manifest=dict(m);manifest.update(worldId=m['worldId']+':'+config['id'],chunks=[dict(id=config['id'],resourceId=chunk['id'],assetIds=sorted(assets),bounds={k:config['trigger'][k] for k in ('minX','maxX','minZ','maxZ')})],resources=[r for r in m['resources'] if r['id'] in assets]+extra+[chunk,overview],overviewResourceId=overview['id'])
    (out/'manifest.json').write_text(json.dumps(manifest,separators=(',',':')),encoding='utf-8')
    subnav={k:[v for v in nav[k] if v.get('roadId',v.get('objectId')) in ids] for k in ('surfaces','ceilings','colliders')}
    (out/'navigation.json').write_text(json.dumps(subnav,separators=(',',':')),encoding='utf-8')
    config['manifestUrl']='/content/scenarios/'+config['id']+'/manifest.json'
    (out/'scenario.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    print(config['id'],len(selected),'objects',len(subnav['surfaces']),'surfaces')
