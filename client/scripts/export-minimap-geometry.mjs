// Export real world geometry for a clean, vector-only top-down map.
import { readFile, writeFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';
import { NullEngine } from '@babylonjs/core/Engines/nullEngine.js';
import { Scene } from '@babylonjs/core/scene.js';
import { Matrix, Vector3, Quaternion } from '@babylonjs/core/Maths/math.vector.js';
import { VertexBuffer } from '@babylonjs/core/Buffers/buffer.js';
import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader.js';
import '@babylonjs/loaders/glTF/2.0/glTFLoader.js';
import '@babylonjs/loaders/glTF/2.0/Extensions/KHR_mesh_quantization.js';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(await readFile(resolve(root,'public/content/world/manifest.json'),'utf8'));
const registry = new Map(manifest.resources.map(r=>[r.id,r]));
async function bytes(r) {
  const data=await readFile(resolve(root,'public',r.url.replace(/^\//,'')));
  return r.encoding==='gzip'?gunzipSync(data):data;
}
const objects=[];
for(const chunk of manifest.chunks){const data=JSON.parse(await bytes(registry.get(chunk.resourceId)));objects.push(...data.objects);}
const groups=Map.groupBy(objects,o=>o.assetId);
const engine=new NullEngine();const scene=new Scene(engine);const triangles=[];
const srgb=v=>Math.round(255*Math.min(1,Math.max(0,v<=.0031308?v*12.92:1.055*Math.pow(v,1/2.4)-.055)));
for(const [id,instances] of groups){
 const resource=registry.get(id);if(resource.kind!=='model')continue;
 const container=await LoadAssetContainerAsync(new Uint8Array(await bytes(resource)),scene,{pluginExtension:'.glb'});
 for(const source of container.meshes.filter(m=>m.getTotalVertices()>0)){
  source.computeWorldMatrix(true);
  const positions=source.getVertexBuffer(VertexBuffer.PositionKind).getFloatData(source.getTotalVertices(),true);
  const normals=source.getVertexBuffer(VertexBuffer.NormalKind)?.getFloatData(source.getTotalVertices(),true);
  const colorBuffer=source.getVertexBuffer(VertexBuffer.ColorKind);
  const colors=colorBuffer?.getFloatData(source.getTotalVertices(),true);
  const colorSize=colorBuffer?.getSize()??4;
  const indices=source.getIndices();
  for(const object of instances){
   const scale=Array.isArray(object.scale)?Vector3.FromArray(object.scale):new Vector3(object.scale,object.scale,object.scale);
   const world=object.matrix?Matrix.FromArray(object.matrix):Matrix.Compose(scale,Quaternion.FromEulerAngles(0,object.heading,0),new Vector3(object.x,object.y??-.1,object.z));
   const transform=source.getWorldMatrix().multiply(world);
   const normalTransform=Matrix.Transpose(Matrix.Invert(transform));
   for(let i=0;i<indices.length;i+=3){
    const ids=[indices[i],indices[i+1],indices[i+2]];
    if(normals){
      const normal=Vector3.TransformNormal(new Vector3(...[0,1,2].map(c=>ids.reduce((n,index)=>n+normals[index*3+c],0)/3)),normalTransform).normalize();
      if(normal.y<=.02)continue;
    }
    const p=ids.map(index=>Vector3.TransformCoordinates(Vector3.FromArray(positions,index*3),transform));
    const area=Math.abs((p[1].x-p[0].x)*(p[2].z-p[0].z)-(p[1].z-p[0].z)*(p[2].x-p[0].x));
    if(area<.003)continue;
    const color=[0,1,2].map(c=>srgb(colors?ids.reduce((n,index)=>n+colors[index*colorSize+c],0)/3:0.4));
    triangles.push({p:p.map(v=>[v.x,v.z]),y:p.reduce((a,v)=>a+v.y,0)/3,color:'#'+color.map(c=>c.toString(16).padStart(2,'0')).join('')});
   }
  }
 }
 container.dispose();
}
await writeFile(process.argv[2],JSON.stringify(triangles));
console.log(`Exported ${triangles.length} top-view triangles from ${objects.length} world objects`);
scene.dispose();engine.dispose();
