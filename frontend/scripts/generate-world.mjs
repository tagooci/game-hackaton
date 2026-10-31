import { mkdir, writeFile } from 'node:fs/promises';

// Один куб переиспользуется всеми объектами. Каждая грань имеет свою нормаль.
const positions = [], normals = [], indices = [];
const faces = [
  [[1,0,0], [[.5,-.5,.5],[.5,-.5,-.5],[.5,.5,-.5],[.5,.5,.5]]],
  [[-1,0,0], [[-.5,-.5,-.5],[-.5,-.5,.5],[-.5,.5,.5],[-.5,.5,-.5]]],
  [[0,1,0], [[-.5,.5,.5],[.5,.5,.5],[.5,.5,-.5],[-.5,.5,-.5]]],
  [[0,-1,0], [[-.5,-.5,-.5],[.5,-.5,-.5],[.5,-.5,.5],[-.5,-.5,.5]]],
  [[0,0,1], [[-.5,-.5,.5],[.5,-.5,.5],[.5,.5,.5],[-.5,.5,.5]]],
  [[0,0,-1], [[.5,-.5,-.5],[-.5,-.5,-.5],[-.5,.5,-.5],[.5,.5,-.5]]],
];
for (const [normal, corners] of faces) {
  const start = positions.length / 3;
  for (const point of corners) { positions.push(...point); normals.push(...normal); }
  indices.push(start,start+1,start+2,start,start+2,start+3);
}
const parts = [new Float32Array(positions), new Float32Array(normals), new Uint16Array(indices)];
const binary = Buffer.concat(parts.map(p => Buffer.from(p.buffer)));
const materials = [
  ['grass', [.24,.43,.23,1]],
  ['terracotta', [.82,.35,.16,1]],
  ['border', [.23,.30,.34,1]],
].map(([name, baseColorFactor]) => ({ name, pbrMetallicRoughness: {
  baseColorFactor, metallicFactor: 0, roughnessFactor: 1,
}}));
const nodes = [];
function box(name, mesh, translation, scale) {
  nodes.push({ name, mesh, translation, scale });
}
box('platform', 0, [0,-.15,0], [30,.3,30]);
for (const x of [-5,5]) for (const z of [-5,5]) {
  box(`marker_${x}_${z}`, 1, [x,.5,z], [1,1,1]);
}
// Внутренняя грань бортика находится ровно на краю площадки: ±15 м.
box('border_west', 2, [-15.15,.3,0], [.3,.6,30.6]);
box('border_east', 2, [15.15,.3,0], [.3,.6,30.6]);
box('border_north', 2, [0,.3,15.15], [30,.6,.3]);
box('border_south', 2, [0,.3,-15.15], [30,.6,.3]);
const gltf = {
  asset: { version: '2.0', generator: 'local-world-generator' },
  scene: 0, scenes: [{ nodes: nodes.map((_,i) => i) }], nodes,
  materials,
  meshes: materials.map((_,material) => ({ primitives: [{
    attributes: { POSITION: 0, NORMAL: 1 }, indices: 2, material,
  }] })),
  buffers: [{ byteLength: binary.length }],
  bufferViews: [
    { buffer: 0, byteOffset: 0, byteLength: parts[0].byteLength, target: 34962 },
    { buffer: 0, byteOffset: parts[0].byteLength, byteLength: parts[1].byteLength, target: 34962 },
    { buffer: 0, byteOffset: parts[0].byteLength + parts[1].byteLength, byteLength: parts[2].byteLength, target: 34963 },
  ],
  accessors: [
    { bufferView: 0, componentType: 5126, count: 24, type: 'VEC3', min: [-.5,-.5,-.5], max: [.5,.5,.5] },
    { bufferView: 1, componentType: 5126, count: 24, type: 'VEC3' },
    { bufferView: 2, componentType: 5123, count: 36, type: 'SCALAR' },
  ],
};
const json = Buffer.from(JSON.stringify(gltf));
const jsonPadded = Buffer.alloc(Math.ceil(json.length / 4) * 4, 0x20);
json.copy(jsonPadded);
const binPadded = Buffer.alloc(Math.ceil(binary.length / 4) * 4);
binary.copy(binPadded);
const header = Buffer.alloc(12);
header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4);
header.writeUInt32LE(12 + 8 + jsonPadded.length + 8 + binPadded.length, 8);
function chunk(type, data) {
  const h = Buffer.alloc(8); h.writeUInt32LE(data.length,0); h.writeUInt32LE(type,4);
  return Buffer.concat([h,data]);
}
const output = new URL('../public/models/world.glb', import.meta.url);
await mkdir(new URL('.', output), { recursive: true });
const file = Buffer.concat([header,chunk(0x4e4f534a,jsonPadded),chunk(0x004e4942,binPadded)]);
await writeFile(output, file);
console.log(`world.glb: ${file.length} bytes; 9 objects; 3 materials; no textures`);
