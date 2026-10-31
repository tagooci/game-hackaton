import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const root = new URL('../public/content/', import.meta.url);
const assets = JSON.parse(await readFile(new URL('asset-catalog.json', root)));
const TILE = 10, CHUNK = 100;
// Координаты сетки: положительное Z направлено на север.
const rawNodes = {
 A:[0,0],T1:[50,0],T2:[145,0],B:[190,0],
 T3:[0,40],X1:[50,40],O1:[145,40],T4:[190,40],
 C:[190,80],D:[240,80],T5:[50,80],E:[95,80],
 T6:[0,120],O2:[50,120],X2:[95,120],X3:[145,120],T7:[240,120],
 H:[0,150],X4:[50,150],T8:[95,150],F:[145,145],G:[190,145],
 I:[50,180],T9:[120,180],X5:[190,180],T10:[240,180],
 J:[120,200],T11:[190,200],K:[240,200],
};
const chains = [
 ['A','T1','T2','B'],['A','T3','T6','H'],['B','T4','C','D','T7','T10','K'],
 ['T3','X1','O1','T4'],['T1','X1','T5','O2','X4','I'],
 ['T2','O1','X3','F','G','X5','T11'],['T5','E','X2','T8'],
 ['T6','O2','X2','X3','T7'],['H','X4','T8'],['I','T9','X5','T10'],
 ['T9','J','T11','K'],
];
const nodes = Object.fromEntries(Object.entries(rawNodes).map(([id,[x,z]])=>[id,{id,x:x*TILE-1200,z:1000-z*TILE,neighbors:[]} ]));
const edges=[];
for(const chain of chains)for(let i=1;i<chain.length;i++){
 const a=nodes[chain[i-1]],b=nodes[chain[i]];
 if(a.x!==b.x && a.z!==b.z)throw Error(`Non-axis edge ${a.id}-${b.id}`);
 edges.push({id:`${a.id}-${b.id}`,from:a.id,to:b.id});a.neighbors.push(b.id);b.neighbors.push(a.id);
}
// Односторонняя боковая петля: отделение от обхода и возвращение в поток.
// Отдельные порты узлов добавлены до раскладки дорожных модулей.
function splitEdge(aid,bid,id,point){
 const index=edges.findIndex(e=>(e.from===aid&&e.to===bid)||(e.to===aid&&e.from===bid));
 if(index<0)throw Error('Missing split edge');
 edges.splice(index,1);const a=nodes[aid],b=nodes[bid];
 a.neighbors=a.neighbors.filter(n=>n!==bid);b.neighbors=b.neighbors.filter(n=>n!==aid);
 nodes[id]={id,x:point[0],z:point[1],neighbors:[aid,bid]};a.neighbors.push(id);b.neighbors.push(id);
 edges.push({id:`${aid}-${id}`,from:aid,to:id},{id:`${id}-${bid}`,from:id,to:bid});
}
splitEdge('T4','C','EXIT',[700,450]);splitEdge('EXIT','C','ENTRY',[700,250]);
for(const [id,x,z] of [['R1',900,450],['R2',900,250]])nodes[id]={id,x,z,neighbors:[]};
for(const [a,b] of [['EXIT','R1'],['R1','R2'],['R2','ENTRY']]){
 nodes[a].neighbors.push(b);nodes[b].neighbors.push(a);
 edges.push({id:`${a}-${b}`,from:a,to:b,oneWay:true});
}
const chunks=new Map();
function getChunk(x,z){
 const cx=Math.floor(x/CHUNK),cz=Math.floor(z/CHUNK),id=`road-${cx}-${cz}`;
 if(!chunks.has(id))chunks.set(id,{id,bounds:{minX:cx*CHUNK,maxX:(cx+1)*CHUNK,minZ:cz*CHUNK,maxZ:(cz+1)*CHUNK},objects:[],lanes:[],signs:[],stopLines:[],obstacles:[],triggers:[],conflictAreas:[]});
 return chunks.get(id);
}
const r=v=>Math.round(v*1000)/1000;
const placed=new Map();
function tile(id,assetId,x,z,heading=0,scale=TILE){
 const key=`${x},${z}`;
 if(placed.has(key))throw Error(`Duplicate tile ${key}: ${id}, ${placed.get(key)}`);
 placed.set(key,id);
 getChunk(x,z).objects.push({id,assetId,x,z,heading:r(heading),scale});
}
const direction=(a,b)=>[Math.sign(b.x-a.x),Math.sign(b.z-a.z)];
// road-straight направлен вдоль X; базовые порты bend/intersection
// фиксируются после проверки импортированных моделей (см. asset-orientation).
function headingFor(ports,base){
 for(let quarter=0;quarter<4;quarter++){
  const angle=quarter*Math.PI/2;
  const turn=base.map(([x,z])=>[Math.round(x*Math.cos(angle)+z*Math.sin(angle)),Math.round(-x*Math.sin(angle)+z*Math.cos(angle))]);
  if(turn.every(p=>ports.some(q=>p[0]===q[0]&&p[1]===q[1])))return angle;
 }
 throw Error(`No matching rotation ${JSON.stringify(ports)}`);
}
for(const n of Object.values(nodes)){
 const ports=n.neighbors.map(id=>direction(n,nodes[id]));
 if(n.id.startsWith('O')){tile(n.id,'road-roundabout',n.x,n.z);continue;}
 let asset='road-crossroad',heading=0;
 if(ports.length===2){
  if(ports[0][0]===-ports[1][0]&&ports[0][1]===-ports[1][1]){asset='road-straight';heading=ports[0][0]?0:Math.PI/2;}
  else {asset='road-bend';heading=headingFor(ports,[[-1,0],[0,-1]]);}
 } else if(ports.length===3){asset='road-intersection';heading=headingFor(ports,[[1,0],[-1,0],[0,-1]]);}
 else if(ports.length!==4)throw Error(`Invalid degree ${n.id}: ${ports.length}`);
 tile(n.id,asset,n.x,n.z,heading);
}
let laneCount=0;
for(const edge of edges){
 const a=nodes[edge.from],b=nodes[edge.to],dx=b.x-a.x,dz=b.z-a.z;
 const length=Math.hypot(dx,dz),ux=dx/length,uz=dz/length,steps=Math.round(length/TILE);
 const trimA=a.id.startsWith('O')?2:1,trimB=b.id.startsWith('O')?2:1;
 for(let i=trimA;i<=steps-trimB;i++){
  const x=a.x+ux*i*TILE,z=a.z+uz*i*TILE;
  tile(`${edge.id}:${i}`,'road-straight',x,z,ux?0:Math.PI/2);
 }
 // Направленные линии разделены по пространственным участкам.
 // Участки включают общий конечный узел, поэтому линия на стыке непрерывна.
 for(let i=0;i<steps;i++)for(const sign of edge.oneWay?[1]:[1,-1]){
  const offset=2;
  const p={x:r(a.x+ux*i*TILE+uz*offset*sign),z:r(a.z+uz*i*TILE-ux*offset*sign)};
  const q={x:r(p.x+ux*TILE),z:r(p.z+uz*TILE)};
  const id=`lane:${edge.id}:${sign}:${i}`;
  const centerline=sign===1?[p,q]:[q,p];
  getChunk((p.x+q.x)/2,(p.z+q.z)/2).lanes.push({id,roadId:edge.id,width:4,direction:'forward',centerline,
   nextLaneIds:i+(sign===1?1:-1)>=0&&i+(sign===1?1:-1)<steps?[`lane:${edge.id}:${sign}:${i+sign}`]:[],
  });laneCount++;
 }
}
// Один источник координат стоп-линий, знаков и видимых линий на подходах.
for(const n of Object.values(nodes)){
 if(!n.id.startsWith('X')&&!n.id.startsWith('O')&&!n.id.startsWith('T'))continue;
 const chunk=getChunk(n.x,n.z);
 const kind=n.id==='X1'||n.id==='X5'?'signals':n.id==='X4'?'stop':n.id==='X2'?'equal':n.id.startsWith('O')?'roundabout':'priority';
 chunk.conflictAreas.push({id:`conflict:${n.id}`,junctionId:n.id,kind,polygon:[{x:n.x-4,z:n.z-4},{x:n.x+4,z:n.z-4},{x:n.x+4,z:n.z+4},{x:n.x-4,z:n.z+4}],routes:[]});
 for(const otherId of n.neighbors){
  const [ux,uz]=direction(n,nodes[otherId]);const distance=n.id.startsWith('O')?17:6;
  const cx=n.x+ux*distance-uz*2,cz=n.z+uz*distance+ux*2;
  const heading=Math.atan2(-ux,-uz);
  const line={id:`stop:${n.id}:${otherId}`,junctionId:n.id,a:{x:cx-uz*1.7,z:cz+ux*1.7},b:{x:cx+uz*1.7,z:cz-ux*1.7},normal:{x:-ux,z:-uz},laneIds:[]};
  // Стоп-линии показываем только там, где установлен STOP или светофор.
  if(kind==='stop'||kind==='signals')chunk.stopLines.push(line);
  if(kind==='stop'||kind==='signals')chunk.signs.push({id:`sign:${n.id}:${otherId}`,type:kind==='stop'?'stop':'signal',x:n.x+ux*distance-uz*4.6,z:n.z+uz*distance+ux*4.6,heading,laneIds:[],signalId:kind==='signals'?`signal:${n.id}:${otherId}`:null});
 }
}
const serialized=[];
for(const chunk of chunks.values()){
 const data=Buffer.from(JSON.stringify(chunk));const filename=`world/chunks/${chunk.id}.json`;
 await mkdir(new URL('world/chunks/',root),{recursive:true});await writeFile(new URL(filename,root),data);
 const resources=[...new Set(chunk.objects.map(o=>o.assetId))];
 for(const s of chunk.signs)resources.push(s.type==='stop'?'road-sign-stop':'traffic-light');
 serialized.push({id:chunk.id,bounds:chunk.bounds,resourceId:chunk.id,assetIds:[...new Set(resources)],resource:{id:chunk.id,url:`/content/${filename}`,kind:'data',bytes:data.length,sha256:createHash('sha256').update(data).digest('hex')}});
}
const overview={nodes:Object.values(nodes).map(({neighbors,...n})=>n),edges};
const overviewData=Buffer.from(JSON.stringify(overview));await writeFile(new URL('world/overview.json',root),overviewData);
const overviewResource={id:'road-overview',url:'/content/world/overview.json',kind:'data',bytes:overviewData.length,sha256:createHash('sha256').update(overviewData).digest('hex')};
const used=new Set(serialized.flatMap(c=>c.assetIds));used.add('sedan');used.add('truck');
const resources=[...Object.values(assets).filter(a=>used.has(a.id)),...serialized.map(c=>c.resource),overviewResource];
const unique=new Map(resources.map(r=>[r.sha256,r]));
const worldBytes=[...unique.values()].reduce((n,r)=>n+r.bytes,0);
const manifest={worldId:'road-network',contentVersion:'roads-preview-01',accounting:'unique_resource_bytes',worldBytes,cacheBudgetBytes:Math.floor(worldBytes*.1),tileSize:TILE,chunkSize:CHUNK,
 bounds:{minX:-1250,maxX:1250,minZ:-1050,maxZ:1050},
 vehicleReference:{car:{assetId:'sedan',length:4.5,width:1.8,height:1.55},truck:{assetId:'truck',length:7.2,width:2.5,height:3.2}},
 spawn:{x:nodes.X1.x+25,z:nodes.X1.z-2,heading:Math.PI/2},
 resources,chunks:serialized.map(({resource,...c})=>c),overviewResourceId:overviewResource.id,
 stats:{tiles:placed.size,chunks:chunks.size,lanes:laneCount,junctions:Object.values(nodes).filter(n=>n.neighbors.length>=3).length}};
await writeFile(new URL('world/manifest.json',root),JSON.stringify(manifest,null,2)+'\n');
console.log(JSON.stringify({worldBytes,budget:manifest.cacheBudgetBytes,...manifest.stats},null,2));
