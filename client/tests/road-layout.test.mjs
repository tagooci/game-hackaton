import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';

const root = new URL('../public/content/', import.meta.url);
const manifest = JSON.parse(await readFile(new URL('world/manifest.json', root)));
const nav = JSON.parse(await readFile(new URL('world/navigation.json', root)));
const nodes = new Map(nav.nodes.map(node => [node.id, node]));
const objects = [];
for (const chunk of manifest.chunks) objects.push(...JSON.parse(await readFile(new URL(`world/chunks/${chunk.id}.json`, root))).objects);

// Проверяем реальные границы GLB, включая отражение X при импорте glTF в Babylon.
async function triangles(assetId) {
  const resource = manifest.resources.find(r => r.id === assetId);
  const bytes = await readFile(new URL(resource.url.slice('/content/'.length), root));
  const size = bytes.readUInt32LE(12), doc = JSON.parse(bytes.subarray(20, 20 + size));
  const data = bytes.subarray(28 + size);
  function values(index) {
    const a = doc.accessors[index], view = doc.bufferViews[a.bufferView];
    const count = {VEC3:3, VEC4:4, SCALAR:1}[a.type];
    const [width, read] = {5122:[2,'readInt16LE'],5123:[2,'readUInt16LE'],5126:[4,'readFloatLE']}[a.componentType];
    return Array.from({length:a.count}, (_,i) => Array.from({length:count}, (_,j) =>
      data[read]((view.byteOffset ?? 0) + (a.byteOffset ?? 0) + i*(view.byteStride ?? count*width) + j*width)));
  }
  const result=[];
  for (const node of doc.nodes) if (node.mesh !== undefined) {
    assert.equal(node.rotation, undefined, 'Update geometry test when importing rotated nodes');
    for (const primitive of doc.meshes[node.mesh].primitives) {
      const points = values(primitive.attributes.POSITION).map(p => p.map((v,i) =>
        (v*(node.scale?.[i] ?? 1)+(node.translation?.[i] ?? 0))*(i===0?-1:1)));
      const indices=values(primitive.indices).flat();
      for(let i=0;i<indices.length;i+=3) result.push(indices.slice(i,i+3).map(index=>points[index]));
    }
  }
  return result;
}
function topAt(triangles,x,z) {
  const hits=[];
  for(const [a,b,c] of triangles) {
    const den=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2]);
    if(Math.abs(den)<1e-10)continue;
    const u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/den;
    const v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/den;
    if(Math.min(u,v,1-u-v)>=-1e-6)hits.push(u*a[1]+v*b[1]+(1-u-v)*c[1]);
  }
  return Math.max(...hits);
}

test('every directed lane and road is reachable, with no dead ends', () => {
  for(const graph of [nodes,new Map(nav.lanes.map(lane=>[lane.id,{neighbors:lane.nextLaneIds}]))]) {
    const visited=new Set(), queue=[graph.keys().next().value];
    while(queue.length){const id=queue.pop();if(visited.has(id))continue;visited.add(id);assert.ok(graph.has(id),id);queue.push(...graph.get(id).neighbors);}
    assert.equal(visited.size,graph.size);
  }
  assert.ok(nav.nodes.every(node=>node.neighbors.length>=2));
});

test('actual Kenney road openings match every tile connection', async () => {
  const meshes = new Map();
  for(const id of ['road-straight','road-bend','road-intersection','road-crossroad','road-level-crossing']) meshes.set(id,await triangles(id));
  for(const object of objects) {
    if(!meshes.has(object.assetId))continue;
    const node=nodes.get(object.id);assert.ok(node,object.id);
    for(const [dx,dz] of [[1,0],[-1,0],[0,1],[0,-1]]) {
      const angle=object.heading, x=dx*Math.cos(angle)-dz*Math.sin(angle),z=dx*Math.sin(angle)+dz*Math.cos(angle);
      const actual=Math.abs(topAt(meshes.get(object.assetId),x*.495,z*.495)-.01)<.001;
      const expected=node.neighbors.some(id=>{const n=nodes.get(id);return Math.sign(n.x-node.x)===dx && Math.sign(n.z-node.z)===dz});
      // На переезде бордюр опущен и поперечные стороны открыты для рельсов.
      if (object.assetId !== 'road-level-crossing' || expected) assert.equal(actual,expected,`${object.id} ${object.assetId}: ${dx},${dz}`);
    }
  }
});

test('road tiles never overlap at one level', () => {
  const tiles=objects.filter(o=>o.assetId.startsWith('road-')&&o.assetId!=='road-roundabout');
  for(let i=0;i<tiles.length;i++)for(let j=i+1;j<tiles.length;j++) {
    const a=tiles[i],b=tiles[j];
    assert.ok(Math.abs(a.x-b.x)>=10 || Math.abs(a.z-b.z)>=10 || Math.abs(a.y-b.y)>4,`${a.id} overlaps ${b.id}`);
  }
});

test('sleepers end at crossing boundaries; inset rails are above asphalt', async () => {
  const crossings=nav.features.filter(f=>f.type==='rail-crossing');
  for(const rail of objects.filter(o=>o.assetId==='railroad-straight')) {
    const halfLength=rail.scale[2]*2;
    for(const crossing of crossings) assert.ok(rail.x+halfLength<=crossing.x-5+.001 || rail.x-halfLength>=crossing.x+5-.001);
  }
  const inset=await triangles('railroad-crossing');
  assert.ok(topAt(inset,0,.6)>.005);
  assert.equal(objects.filter(o=>o.assetId==='railroad-crossing').length,crossings.length);
});
