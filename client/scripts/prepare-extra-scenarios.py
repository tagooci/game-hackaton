"""Export scenarios 1 and 5 from published world tiles; original world is unchanged."""
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
first=dict(id='left-turn',contentFolder='left-turn-v2',number=1,title='Грузовик поворачивает',kind='junction',center=[60,20],requiredPlayers=3,timeLimitSeconds=90,
 trigger=dict(minX=50,maxX=65,minZ=0,maxZ=43,minY=-.2,maxY=2.5),roleIds=['south-left','truck-right','north-follow'],
 roles=[role('south-left','Поверните налево на запад. Учитывайте оба встречных автомобиля.',pose(61.5,7,0),pose(44,21.5,-math.pi/2),line((61.5,7),(61.5,13.5))+curve([(61.5,13.5),(61.5,18),(58,21.5),(53.5,21.5)])+line((53.5,21.5),(44,21.5))),
 role('truck-right','Поверните направо на запад. Сохраняйте свою полосу на общем выезде.',pose(58.5,33,math.pi),pose(48,21.5,-math.pi/2),line((58.5,33),(58.5,25.5))+curve([(58.5,25.5),(58.5,23),(56,21.5),(53.5,21.5)])+line((53.5,21.5),(48,21.5))),
 role('north-follow','Следуйте за грузовиком и проедьте перекрёсток прямо на юг.',pose(58.5,41,math.pi),pose(58.5,7,math.pi),line((58.5,41),(58.5,7)))],
 yieldsTo={'south-left':['truck-right','north-follow']},signs=[dict(kind='priority',x=64.4,z=12,heading=math.pi),dict(kind='priority',x=55.6,z=28,heading=0),dict(kind='yield',x=52,z=15.6,heading=-math.pi/2)])
first['roles'][1]['vehicleType']='truck'
bridge=dict(id='bridge-junction',number=5,title='Перекрёсток у моста',kind='junction',center=[20,-40],queuePoint=[35,-40],requiredPlayers=4,timeLimitSeconds=90,finishMode='pass',
 trigger=dict(minX=26,maxX=45,minZ=-45,maxZ=-35,minY=-.2,maxY=2.5),roleIds=['ramp-left','east-straight','west-straight','east-left'],
 roles=[role('ramp-left','Спуститесь с моста и поверните налево на запад, уступая главной дороге.',pose(21.5,-52,0),pose(13,-38.5,-math.pi/2),line((21.5,-52),(21.5,-46.5))+curve([(21.5,-46.5),(21.5,-42),(18,-38.5),(13.5,-38.5)])+line((13.5,-38.5),(13,-38.5))),
 role('east-straight','Проедьте прямо по главной дороге на запад.',pose(29,-38.5,-math.pi/2),pose(9,-38.5,-math.pi/2),line((29,-38.5),(9,-38.5))),
 role('west-straight','Проедьте прямо по главной дороге на восток.',pose(8,-41.5,math.pi/2),pose(34,-41.5,math.pi/2),line((8,-41.5),(34,-41.5))),
 role('east-left','Следуйте за автомобилем впереди, затем поверните налево на мост. Уступите встречному.',pose(37,-38.5,-math.pi/2),pose(18.5,-53,math.pi),line((37,-38.5),(26.5,-38.5))+curve([(26.5,-38.5),(22,-38.5),(18.5,-42),(18.5,-46.5)])+line((18.5,-46.5),(18.5,-53)))],
 yieldsTo={'ramp-left':['east-straight','west-straight','east-left'],'east-left':['west-straight']},
 signs=[dict(kind='priority',x=27,z=-44.4,heading=-math.pi/2),dict(kind='priority',x=13,z=-35.6,heading=math.pi/2),dict(kind='yield',x=24.4,z=-47,heading=math.pi)])
configs=[(first,{'Compact_001_road-straight','Compact_002_road-straight','Compact_003_road-intersection-path','Compact_004_road-straight','Compact_005_road-straight','S01 - STOCK CURVED ASCENT'}),
 (bridge,{'Compact_097_road-roundabout','Compact_037_road-intersection-path','Compact_030_road-crossroad-path','Compact_019_road-straight','Compact_015_road-intersection-path','U01 - STOCK CURVED ASCENT','U02 - U TURN WEST HALF','U03 - U TURN EAST HALF','U04 - STOCK CURVED DESCENT'})]
for config,ids in configs:
    folder=config.get('contentFolder',config['id']);out=ROOT/'content/scenarios'/folder;out.mkdir(parents=True,exist_ok=True)
    selected=[o for o in objects if o['id'] in ids]
    assert len(selected)==len(ids),(config['id'],ids-{o['id'] for o in selected})
    extra=[]
    if config['signs']:
        signs=read(ROOT.parents[1]/'blender/scenario-signs/resources.json')
        extra=[r for r in signs if r['id'] in {'sign-'+s['kind'] for s in config['signs']}]
        selected += [dict(id=f'scenario-sign-{i}',assetId='sign-'+s['kind'],x=s['x'],y=.1,z=s['z'],heading=s['heading'],scale=1) for i,s in enumerate(config['signs'])]
    def resource(name,data):
        data=gzip.compress(json.dumps(data,separators=(',',':')).encode(),mtime=0);(out/name).write_bytes(data)
        return dict(id=config['id']+'-'+name,kind='data',url='/content/scenarios/'+folder+'/'+name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),encoding='gzip')
    chunk=resource('junction.json.bin',dict(objects=selected,signs=[]));overview=resource('overview.json.bin',{})
    assets={o['assetId'] for o in selected}
    manifest=dict(m);manifest.update(worldId=m['worldId']+':'+config['id'],chunks=[dict(id=config['id'],resourceId=chunk['id'],assetIds=sorted(assets),bounds={k:config['trigger'][k] for k in ('minX','maxX','minZ','maxZ')})],resources=[r for r in m['resources'] if r['id'] in assets]+extra+[chunk,overview],overviewResourceId=overview['id'])
    (out/'manifest.json').write_text(json.dumps(manifest,separators=(',',':')),encoding='utf-8')
    subnav={k:[v for v in nav[k] if v.get('roadId',v.get('objectId')) in ids] for k in ('surfaces','ceilings','colliders')}
    (out/'navigation.json').write_text(json.dumps(subnav,separators=(',',':')),encoding='utf-8')
    config['type'] = 'long' if config['id'] == 'bridge-junction' else 'short'
    config['version'] = 1
    config['rules'] = {'coverage': {'roadMarkings': False, 'rightOfWay': True, 'trafficSigns': True, 'collisions': True}}
    if config['type'] == 'long':
        config['timeLimitSeconds'] = 180
    config['manifestUrl']='/content/scenarios/'+folder+'/manifest.json'
    (out/'scenario.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    print(config['id'],len(selected),'objects',len(subnav['surfaces']),'surfaces')
