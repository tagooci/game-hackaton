import assert from 'node:assert/strict';
import { test } from 'node:test';
import { NullEngine } from '@babylonjs/core/Engines/nullEngine.js';
import { Scene } from '@babylonjs/core/scene.js';
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder.js';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial.js';
import { RoadContent } from '../src/world/road-content.js';

function setup(t) {
  const engine = new NullEngine();
  const scene = new Scene(engine);
  const source = MeshBuilder.CreateGround('source', {}, scene);
  source.material = new StandardMaterial('road-material', scene);
  // GPU-компиляция проверяется в браузере; здесь проверяем жизненный цикл meshes.
  source.material.forceCompilationAsync = async () => {};
  const road = new RoadContent(scene, () => {});
  const resource = id => ({ id, sha256: id, bytes: 10, kind: id === 'model' ? 'model' : 'data' });
  road.registry = new Map(['overview', 'a', 'b', 'model'].map(id => [id, resource(id)]));
  road.manifest = {
    chunkSize: 100, overviewResourceId: 'overview',
    chunks: [0, 200].map((x, index) => ({ resourceId: index ? 'b' : 'a', assetIds: ['model'], bounds: {minX: x, maxX: x + 100, minZ: 0, maxZ: 100} })),
  };
  road.budget = 100;
  road.acquire = async resource => {
    if (road.loaded.has(resource.sha256)) return road.loaded.get(resource.sha256);
    const value = resource.kind === 'model' ? {meshes: [source], dispose() {}} : {
      objects: resource.id === 'overview' ? [] : [{assetId: 'model', x: resource.id === 'a' ? 50 : 250, z: 50, scale: 1, heading: 0}], signs: [],
    };
    const entry = {resource, value};
    road.loaded.set(resource.sha256, entry);
    return entry;
  };
  t.after(async () => { road.dispose(); await road.serial.catch(() => {}); scene.dispose(); engine.dispose(); });
  return road;
}

test('old road stays visible while downloading; common meshes survive the swap', async t => {
  const road = setup(t);
  await road.update(50, 50);
  const mesh = road.rendered[0];
  let release;
  const download = road.acquire.bind(road);
  road.acquire = async resource => {
    if (resource.id === 'b' && !road.loaded.has('b')) await new Promise(resolve => { release = resolve; });
    return download(resource);
  };
  const updating = road.update(150, 50);
  while (!release) await Promise.resolve();
  assert.equal(road.rendered[0], mesh);
  assert.equal(mesh.isEnabled(), true);
  assert.equal(mesh.thinInstanceCount, 1);
  release();
  await updating;
  assert.equal(road.rendered[0], mesh);
  assert.equal(mesh.thinInstanceCount, 2);
  await road.update(350, 50);
  assert.equal(road.rendered[0], mesh);
  assert.equal(mesh.thinInstanceCount, 1);
  assert.equal(road.loaded.has('a'), false);
});

test('failed download keeps the previous road and clears incomplete resources', async t => {
  const road = setup(t);
  await road.update(50, 50);
  const mesh = road.rendered[0];
  const download = road.acquire.bind(road);
  road.acquire = resource => resource.id === 'b' ? Promise.reject(new Error('download failed')) : download(resource);
  await assert.rejects(road.update(150, 50), /download failed/);
  assert.equal(road.rendered[0], mesh);
  assert.equal(mesh.isEnabled(), true);
  assert.equal(mesh.thinInstanceCount, 1);
  assert.equal(road.loaded.has('a'), true);
});


test('mirrored glTF keeps front-face orientation and never mutates source indices', async t => {
  const road = setup(t);
  const { value: container } = await road.acquire(road.registry.get('model'));
  const source = container.meshes[0];
  source.scaling.z = -1;
  source.sideOrientation = 0; // Clockwise, как у glTF в левой системе координат.
  source.computeWorldMatrix(true);
  const originalIndices = Array.from(source.getIndices());
  await road.update(50, 50);
  const mesh = road.rendered[0];
  assert.equal(mesh.sideOrientation, source.sideOrientation);
  assert.deepEqual(Array.from(source.getIndices()), originalIndices);
  const indices = Array.from(mesh.getIndices());
  for (let i = 0; i < indices.length; i += 3) {
    assert.deepEqual(indices.slice(i, i + 3), [originalIndices[i], originalIndices[i + 2], originalIndices[i + 1]]);
  }
  // Повторное создание после выгрузки не должно снова перевернуть источник.
  await road.update(1050, 50);
  await road.update(50, 50);
  assert.deepEqual(Array.from(source.getIndices()), originalIndices);
  assert.deepEqual(Array.from(road.rendered[0].getIndices()), indices);
});

test('the real map can be traversed without cache overflow or missing nearby chunks', async t => {
  const { readFile } = await import('node:fs/promises');
  const { gunzipSync } = await import('node:zlib');
  const root = new URL('../public/content/', import.meta.url);
  const manifest = JSON.parse(await readFile(new URL('world/manifest.json', root)));
  const navigation = JSON.parse(await readFile(new URL('world/navigation.json', root)));
  const road = setup(t);
  const source = (await road.acquire(road.registry.get('model'))).value.meshes[0];
  road.loaded.clear();
  road.manifest = manifest;
  road.budget = manifest.cacheBudgetBytes;
  road.registry = new Map(manifest.resources.map(resource => [resource.id, resource]));
  const data = new Map();
  for (const resource of manifest.resources) if (resource.kind === 'data') {
    const bytes = await readFile(new URL(resource.url.slice('/content/'.length), root));
    data.set(resource.id, JSON.parse(resource.encoding === 'gzip' ? gunzipSync(bytes) : bytes));
  }
  // Настоящие размеры и JSON карты; GPU и парсинг GLB проверяются отдельно.
  road.acquire = async resource => {
    if (road.loaded.has(resource.sha256)) return road.loaded.get(resource.sha256);
    assert.ok(road.stats().activeBytes + resource.bytes <= road.budget, resource.id);
    const entry = {resource, value: resource.kind === 'model' ? {meshes:[source], dispose(){}} : data.get(resource.id)};
    road.loaded.set(resource.sha256, entry);
    return entry;
  };
  const nodes = new Map(navigation.nodes.map(node => [node.id, node])), visited = new Set();
  async function move(node) {
    await road.update(node.x, node.z);
    for (const chunk of manifest.chunks) {
      const b=chunk.bounds;
      if (Math.hypot(Math.max(b.minX-node.x,0,node.x-b.maxX),Math.max(b.minZ-node.z,0,node.z-b.maxZ)) < manifest.streamRadius) {
        assert.ok(road.loaded.has(road.registry.get(chunk.resourceId).sha256), chunk.id);
      }
    }
  }
  async function visit(id) {
    visited.add(id);
    const node=nodes.get(id);
    await move(node);
    for (const next of node.neighbors) if (!visited.has(next)) { await visit(next); await move(node); }
  }
  await visit(navigation.nodes[0].id);
  assert.equal(visited.size, navigation.nodes.length);
});
