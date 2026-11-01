import { readFile, writeFile, mkdir, readdir, unlink } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const root = new URL('../public/content/', import.meta.url);
const assets = JSON.parse(await readFile(new URL('asset-catalog.json', root)));
const TILE = 10, CHUNK = 20;
const nodes = new Map();
const height = z => Math.max(0, Math.min(5, (65 - Math.abs(z)) * .1));
const crossingRoads = new Set([-200,-100,0,100,200]);
function addPath(points, raised = false) {
  let previous;
  for (let i = 1; i < points.length; i++) {
    const [ax, az] = points[i - 1], [bx, bz] = points[i];
    if (ax !== bx && az !== bz) throw Error('Paths must follow the tile grid');
    const steps = (Math.abs(bx - ax) + Math.abs(bz - az)) / TILE;
    for (let k = i === 1 ? 0 : 1; k <= steps; k++) {
      const x = ax + (bx - ax) * k / steps, z = az + (bz - az) * k / steps;
      const y = raised ? height(z) : 0;
      const id = `${x}:${z}:${y > 0 ? 'bridge' : 'ground'}`;
      if (!nodes.has(id)) nodes.set(id, {id, x, y, z, neighbors: new Set()});
      const current = nodes.get(id);
      if (previous && previous.id !== id) { previous.neighbors.add(id); current.neighbors.add(previous.id); }
      previous = current;
    }
  }
}
// Небольшая замкнутая сеть. У моста нет наземных примыканий на склонах.
addPath([[0,-180],[0,180]], true);
addPath([[-200,0],[200,0]]);
addPath([[-200,-180],[-200,180],[200,180],[200,-180],[-200,-180]]);
for (const side of [-1,1]) {
  const x = value => side * value;
  addPath([[x(100),-180],[x(100),180]]);
  addPath([[x(150),-100],[x(150),100]]);
  for (const z of [-100,100]) addPath([[x(200),z],[x(100),z]]);
  for (const z of [-80,80]) addPath([[x(100),z],[0,z]]);
  addPath([[x(40),-80],[x(40),80]]);
}
// Поперечные связи разбивают длинные прямые на короткие кварталы.
for (const z of [-140,140]) addPath([[-200,z],[200,z]]);

// Проверяем весь дорожный граф, включая оба подъезда на мост.
const visited = new Set(), queue = [nodes.values().next().value.id];
while (queue.length) {
  const id = queue.pop(); if (visited.has(id)) continue;
  visited.add(id); for (const next of nodes.get(id).neighbors) queue.push(next);
}
if (visited.size !== nodes.size) throw Error(`Disconnected roads: ${nodes.size - visited.size}`);
if ([...nodes.values()].some(n => n.neighbors.size < 2)) throw Error('Unexpected dead end');

const chunks = new Map(), surfaces = [], features = [];
function chunkAt(x,z) {
  const cx = Math.floor(x/CHUNK), cz = Math.floor(z/CHUNK), id = `road-${cx}-${cz}`;
  if (!chunks.has(id)) chunks.set(id, {id,bounds:{minX:cx*CHUNK,maxX:(cx+1)*CHUNK,minZ:cz*CHUNK,maxZ:(cz+1)*CHUNK},objects:[],signs:[]});
  return chunks.get(id);
}
function object(id,assetId,x,z,heading=0,scale=TILE,y=-.1) {
  if (!assets[assetId]) throw Error(`Unknown asset ${assetId}`);
  chunkAt(x,z).objects.push({id,assetId,x,y,z,heading,scale});
}
const direction = (a,b) => [Math.sign(b.x-a.x), Math.sign(b.z-a.z)];
function headingFor(ports,base) {
  for(let quarter=0;quarter<4;quarter++) {
    const angle=quarter*Math.PI/2;
    const rotated=base.map(([x,z])=>[Math.round(x*Math.cos(angle)+z*Math.sin(angle)),Math.round(-x*Math.sin(angle)+z*Math.cos(angle))]);
    if(rotated.every(p=>ports.some(q=>p[0]===q[0]&&p[1]===q[1])))return angle;
  }
  throw Error(`Invalid ports ${JSON.stringify(ports)}`);
}
for (const n of nodes.values()) {
  const ports=[...n.neighbors].map(id=>direction(n,nodes.get(id)));
  let assetId='road-crossroad', heading=0, y=n.y-.1;
  const isRamp=n.id.endsWith('bridge') && Math.abs(n.z)>15 && Math.abs(n.z)<65;
  if (isRamp) {
    assetId='road-ramp';
    // После glTF-импорта локальный +X отражён: подъём идёт к -X.
    heading=n.z>0 ? -Math.PI/2 : Math.PI/2;
    y=Math.min(height(n.z-5),height(n.z+5))-.1;
  } else if (ports.length===2) {
    if (ports[0][0]===-ports[1][0]&&ports[0][1]===-ports[1][1]) {assetId='road-straight';heading=ports[0][0]?0:Math.PI/2;}
    else {assetId='road-bend';heading=headingFor(ports,[[1,0],[0,1]]);}
  } else if (ports.length===3) {assetId='road-intersection';heading=headingFor(ports,[[1,0],[-1,0],[0,1]]);}
  else if (ports.length!==4) throw Error(`Invalid junction ${n.id}`);
  if (n.z===120 && crossingRoads.has(n.x)) assetId='road-level-crossing';
  object(n.id,assetId,n.x,n.z,heading,TILE,y);
  // Поверхности для Python: высота не зависит от отрисовки или загрузки клиента.
  const alongZ=ports.some(p=>p[1]!==0)&&!ports.some(p=>p[0]!==0);
  const z1=n.z-(alongZ?5:0), z2=n.z+(alongZ?5:0);
  surfaces.push({id:n.id,ax:n.x-(alongZ?0:5),az:z1,bx:n.x+(alongZ?0:5),bz:z2,
    ay:isRamp?height(z1):n.y,by:isRamp?height(z2):n.y,width:10});
}
for (const x of [-5.2,5.2]) for (const z of [-12,12]) object(`support:${x}:${z}`,'bridge-pillar',x,z,0,[2,10,2],-.1);
features.push({id:'central-overpass',type:'overpass',x:0,z:0,clearance:4.8});

// Короткий тоннель на юго-западном подходе, без домов над ним.
for (const z of [-55,-45]) object(`tunnel:${z}`,'tunnel-section',-100,z,0,1,0);
features.push({id:'tunnel-west',type:'tunnel',x:-100,z:-50,length:20,clearance:4.8});
const stops=[[-200,40,Math.PI/2],[-100,-155,Math.PI/2],[200,-40,-Math.PI/2]];
stops.forEach(([x,z,heading],i)=>{
  const dx=Math.sin(heading),dz=Math.cos(heading);
  object(`stop:${i}`,'bus-stop',x+dx*7,z+dz*7,heading,1,0);
  features.push({id:`stop:${i}`,type:'bus-stop',x,z});
});
// Переезды строго поперёк дорог. На асфальте — утопленные рельсы,
// обычные шпалы заканчиваются у границ дорожного полотна.
const crossings = [-200,-100,0,100,200];
for (let x=-276;x<280;x+=8) {
  // Обрезаем каждый сегмент по границам переездов, а не кладём шпалы поверх дороги.
  let spans = [[x-4,x+4]];
  for (const roadX of crossings) spans = spans.flatMap(([a,b]) => {
    const lo=roadX-5,hi=roadX+5;
    if (b<=lo || a>=hi) return [[a,b]];
    return [[a,Math.min(b,lo)],[Math.max(a,hi),b]].filter(([l,r])=>r-l>.01);
  });
  for (const [a,b] of spans) object(`rail:${a}:${b}`,'railroad-straight',(a+b)/2,120,Math.PI/2,[2,.8,(b-a)/4],-.07);
}
for (const x of crossings) {
  object(`inset-rail:${x}`,'railroad-crossing',x,120,0,1,0);
  object(`crossing:${x}`,'rail-crossing-sign',x-6.5,113,0,1,0);
  object(`crossing-back:${x}`,'rail-crossing-sign',x+6.5,127,Math.PI,1,0);
  features.push({id:`crossing:${x}`,type:'rail-crossing',x,z:120});
}

const round = value=>Math.round(value*10000)/10000;
const navNodes=[...nodes.values()].map(n=>({...n,neighbors:[...n.neighbors]}));
// Направленный граф полос. Для каждого въезда перечислены все достижимые выезды.
const lanes=[];
for(const n of nodes.values())for(const nextId of n.neighbors) {
  const next=nodes.get(nextId),[dx,dz]=direction(n,next),offset=2;
  lanes.push({id:`${n.id}>${nextId}`,roadId:n.id,width:4,
    centerline:[{x:n.x+dz*offset,y:n.y,z:n.z-dx*offset},{x:next.x+dz*offset,y:next.y,z:next.z-dx*offset}],
    nextLaneIds:[...next.neighbors].filter(id=>id!==n.id).map(id=>`${next.id}>${id}`)});
}
const nav={nodes:navNodes,lanes,surfaces,features,validation:{connected:true,reachableRoads:visited.size,totalRoads:nodes.size,maxTileGap:10}};
const overview={nodes:navNodes.filter(n=>n.neighbors.length!==2).map(({neighbors,...n})=>n),features,edges:[]};
const resources=[];
const hash=data=>createHash('sha256').update(data).digest('hex');
async function dataResource(id,path,value) {
  const data=Buffer.from(JSON.stringify(value));await writeFile(new URL(path,root),data);
  const entry={id,url:`/content/${path}`,kind:'data',bytes:data.length,sha256:hash(data)};resources.push(entry);return entry;
}
await mkdir(new URL('world/chunks/',root),{recursive:true});
for (const file of await readdir(new URL('world/chunks/',root))) if(file.startsWith('road-')&&file.endsWith('.json')) await unlink(new URL(`world/chunks/${file}`,root));
const serialized=[];
for (const chunk of chunks.values()) {
  const resource=await dataResource(chunk.id,`world/chunks/${chunk.id}.json`,chunk);
  serialized.push({id:chunk.id,bounds:chunk.bounds,resourceId:resource.id,assetIds:[...new Set(chunk.objects.map(o=>o.assetId))]});
}
const navigation=await dataResource('road-navigation','world/navigation.json',nav);
const summary=await dataResource('road-overview','world/overview.json',overview);
const used=new Set(serialized.flatMap(c=>c.assetIds));used.add('sedan');used.add('truck');
resources.unshift(...Object.values(assets).filter(asset=>used.has(asset.id)));
const worldBytes=[...new Map(resources.map(resource=>[resource.sha256,resource.bytes])).values()].reduce((sum,bytes)=>sum+bytes,0);
const manifest={worldId:'compact-interchanges-v2',contentVersion:'interchanges-02',accounting:'unique_resource_bytes',worldBytes,cacheBudgetBytes:Math.floor(worldBytes*.1),tileSize:TILE,chunkSize:CHUNK,streamRadius:65,streamStep:2.5,
 bounds:{minX:-290,maxX:290,minZ:-200,maxZ:200},spawn:{x:-185,z:-2,heading:Math.PI/2},
 resources,chunks:serialized,overviewResourceId:summary.id,navigationResourceId:navigation.id,
 stats:{roadTiles:nodes.size,chunks:chunks.size,lanes:lanes.length,junctions:overview.nodes.length,stops:stops.length,crossings:5,bridges:1,tunnels:1,reachableRoads:visited.size}};
await writeFile(new URL('world/manifest.json',root),JSON.stringify(manifest,null,2)+'\n');
console.log(JSON.stringify({worldBytes,budget:manifest.cacheBudgetBytes,...manifest.stats},null,2));
