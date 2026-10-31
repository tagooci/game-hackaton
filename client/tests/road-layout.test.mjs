import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';

const root=new URL('../public/content/',import.meta.url);
const manifest=JSON.parse(await readFile(new URL('world/manifest.json',root)));
const nav=JSON.parse(await readFile(new URL('world/navigation.json',root)));

test('all imported road levels and directed lanes are reachable',()=>{
  for(const graph of [new Map(nav.nodes.map(n=>[n.id,n.neighbors])),new Map(nav.lanes.map(n=>[n.id,n.nextLaneIds]))]){
    const seen=new Set(),queue=[graph.keys().next().value];
    while(queue.length){const id=queue.pop();if(seen.has(id))continue;assert.ok(graph.has(id),id);seen.add(id);queue.push(...graph.get(id));}
    assert.equal(seen.size,graph.size);
  }
});

test('every authored road port has exactly one matching exit at the same height',()=>{
  const ports=nav.sourceRoads.flatMap(road=>road.ports.map(port=>({...port,road:road.object})));
  for(const port of ports){
    const matching=ports.filter(other=>other.road!==port.road&&
      Math.hypot(...port.position.map((v,i)=>v-other.position[i]))<.002&&
      port.direction.every((v,i)=>v===-other.direction[i]));
    assert.equal(matching.length,1,port.road);
    const other=matching[0];
    const gap=(a,b)=>Math.hypot(...a.map((v,i)=>v-b[i]));
    const [a,b]=port.endpoints,[c,d]=other.endpoints;
    assert.ok(Math.min(Math.max(gap(a,c),gap(b,d)),Math.max(gap(a,d),gap(b,c)))<.002,port.road);
  }
});

test('compressed map models are self-contained GLB; instances keep Blender matrices',async()=>{
  for(const resource of manifest.resources.filter(r=>r.kind==='model')){
    const data=gunzipSync(await readFile(new URL(resource.url.slice('/content/'.length),root)));
    assert.equal(data.readUInt32LE(0),0x46546c67);
    const size=data.readUInt32LE(12),doc=JSON.parse(data.subarray(20,20+size));
    assert.ok(!doc.images?.length);
    assert.ok(doc.buffers.every(buffer=>!buffer.uri));
  }
  const registry=new Map(manifest.resources.map(r=>[r.id,r]));
  for(const chunk of manifest.chunks){
    const resource=registry.get(chunk.resourceId);
    const data=JSON.parse(gunzipSync(await readFile(new URL(resource.url.slice('/content/'.length),root))));
    for(const object of data.objects){assert.equal(object.matrix.length,16);assert.ok(object.matrix.every(Number.isFinite));}
  }
});
