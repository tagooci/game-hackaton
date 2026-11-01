import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { NullEngine, Scene, LoadAssetContainerAsync, Matrix, Vector3 } from '@babylonjs/core';
import '@babylonjs/loaders/glTF/index.js';
import { createRoadMesh } from '../src/road-mesh.js';

const root = new URL('../public/content/', import.meta.url);
const engine = new NullEngine();
const scene = new Scene(engine);
const ports = new Map();
for (const id of ['road-straight','road-bend','road-intersection','road-crossroad','road-roundabout']) {
  const bytes = await readFile(new URL(`assets/environment/${id}.glb`,root));
  const container = await LoadAssetContainerAsync(bytes,scene,{pluginExtension:'.glb'});
  const source = container.meshes.find(m=>m.getTotalVertices()>0);
  source.computeWorldMatrix(true);
  const original = Array.from(source.getIndices());
  let reference;
  for (let pass=0;pass<6;pass++) {
    const mesh = createRoadMesh(source,scene,source.getWorldMatrix(),`test:${id}`);
    assert.equal(mesh.sideOrientation,source.sideOrientation,`${id}: glTF face orientation was lost`);
    const indices = Array.from(mesh.getIndices());
    assert.deepEqual(Array.from(source.getIndices()),original,`${id}: source indices were mutated`);
    if (reference) assert.deepEqual(indices,reference,`${id}: triangle winding changed between builds`);
    reference=indices;
    if (pass===0) {
      const vertices=mesh.getVerticesData('position'), result=[];
      const boundary=id==='road-roundabout'?1.5:.5;
      for (const [axis,sign] of [[0,-1],[0,1],[2,-1],[2,1]]) {
        for(let i=0;i<vertices.length;i+=3) {
          if(Math.abs(vertices[i+axis]-sign*boundary)<.0001 && Math.abs(vertices[i+1]-.01)<.0001) {
            result.push(axis===0?[sign,0]:[0,sign]);break;
          }
        }
      }
      ports.set(id,result);
    }
    mesh.dispose(false,false);
  }
  container.dispose();
}
const overview=JSON.parse(await readFile(new URL('world/overview.json',root)));
const manifest=JSON.parse(await readFile(new URL('world/manifest.json',root)));
const nodes=new Map(overview.nodes.map(n=>[n.id,n]));
let checked=0;
for(const chunk of manifest.chunks) {
  const data=JSON.parse(await readFile(new URL(`world/chunks/${chunk.id}.json`,root)));
  for(const object of data.objects) {
    const node=nodes.get(object.id);
    if(!node)continue;
    const expected=overview.edges.filter(e=>e.from===node.id||e.to===node.id).map(e=>{
      const other=nodes.get(e.from===node.id?e.to:e.from);
      return [Math.sign(other.x-node.x),Math.sign(other.z-node.z)].join(',');
    }).sort();
    const matrix=Matrix.RotationY(object.heading);
    const actual=ports.get(object.assetId).map(([x,z])=>{
      const v=Vector3.TransformNormal(new Vector3(x,0,z),matrix);
      return [Math.round(v.x),Math.round(v.z)].join(',');
    }).sort();
    assert.deepEqual(actual,expected,`${node.id}: road openings do not match neighbors`);
    checked++;
  }
}
engine.dispose();
console.log(`Passed: 6 rebuilds of 5 model types; all ${checked} junction/corner orientations match GLB geometry.`);
