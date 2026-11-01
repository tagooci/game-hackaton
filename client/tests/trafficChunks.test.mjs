import test from 'node:test';
import assert from 'node:assert/strict';
import { NullEngine } from '@babylonjs/core/Engines/nullEngine.js';
import { Scene } from '@babylonjs/core/scene.js';
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder.js';
import { AssetContainer } from '@babylonjs/core/assetContainer.js';
import { createTrafficView } from '../src/players/trafficView.ts';
import { RoadContent } from '../src/world/road-content.js';

const flush = () => new Promise(resolve => setImmediate(resolve));
const state = (id, x) => ({ id, model: 'sedan', x, y: .1, z: 2, heading: 0, pitch: 0, speed: 2 });
function model(scene) {
  const container = new AssetContainer(scene);
  container.meshes.push(MeshBuilder.CreateBox('source', { size: 1 }, scene));
  container.populateRootNodes();
  container.removeAllFromScene();
  return container;
}

test('NPC scope uses committed chunks and unloads trimmed bounds', () => {
  const roads = new RoadContent(null, () => {});
  roads.manifest = { overviewResourceId: 'overview' };
  roads.registry = new Map([['overview', { sha256: 'overview' }]]);
  roads.activeChunks = [{ resourceId: 'west', bounds: { minX: -20, maxX: 0, minZ: 0, maxZ: 20 } }];
  assert.equal(roads.hasLoadedChunkAt(-1, 2), true);
  assert.equal(roads.hasLoadedChunkAt(0, 2), false);
  roads.trimDistant(new Set());
  assert.equal(roads.hasLoadedChunkAt(-1, 2), false);
});

test('shared model is released after its last chunk unloads', async () => {
  const engine = new NullEngine(), scene = new Scene(engine), active = new Set();
  let loads = 0, releases = 0;
  const view = createTrafficView(scene, s => active.has(s.x), async () => {
    loads++;
    const container = model(scene), dispose = container.dispose.bind(container);
    container.dispose = () => { releases++; dispose(); };
    return container;
  });
  try {
    view.handleSnapshot([state('one', 1), state('two', 21)]);
    view.update(); await flush(); assert.equal(loads, 0);
    assert.deepEqual(view.stats(), { states: 0, instances: 0, models: 0, pending: 0 });
    active.add(1); active.add(21);
    view.handleSnapshot([state('one', 1), state('two', 21)]);
    view.update(); await flush(); assert.equal(loads, 1);
    assert.ok(scene.getTransformNodeByName('traffic-one'));
    active.delete(1); view.update();
    assert.equal(scene.getTransformNodeByName('traffic-one'), null);
    assert.ok(scene.getTransformNodeByName('traffic-two'));
    assert.equal(releases, 0);
    assert.equal(view.stats().states, 1);
    active.clear(); view.update(); assert.equal(releases, 1);
    assert.deepEqual(view.stats(), { states: 0, instances: 0, models: 0, pending: 0 });
    active.add(1); view.update(); await flush();
    assert.equal(loads, 1);
    view.handleSnapshot([state('one', 1)]); view.update(); await flush();
    assert.equal(loads, 2);
    assert.ok(scene.getTransformNodeByName('traffic-one'));
  } finally { view.dispose(); scene.dispose(); engine.dispose(); }
});

test('late loading result is disposed after its chunk disappears', async () => {
  const engine = new NullEngine(), scene = new Scene(engine);
  let active = true, resolve, signal, released = false;
  const view = createTrafficView(scene, () => active, (_model, abortSignal) => {
    signal = abortSignal;
    return new Promise(done => { resolve = done; });
  });
  try {
    view.handleSnapshot([state('late', 1)]); view.update();
    active = false; view.update(); assert.equal(signal.aborted, true);
    const container = model(scene), dispose = container.dispose.bind(container);
    container.dispose = () => { released = true; dispose(); };
    resolve(container); await flush();
    assert.equal(released, true);
    assert.equal(scene.getTransformNodeByName('traffic-late'), null);
  } finally { view.dispose(); scene.dispose(); engine.dispose(); }
});

test('entering a scenario clears NPCs and ignores world traffic snapshots', async () => {
  const engine = new NullEngine(), scene = new Scene(engine);
  let loads = 0;
  const view = createTrafficView(scene, () => true, async () => { loads++; return model(scene); });
  try {
    view.handleSnapshot([state('world', 1)]); view.update(); await flush();
    assert.ok(scene.getTransformNodeByName('traffic-world'));
    view.setEnabled(false);
    view.handleSnapshot([state('world', 1)]); view.update(); await flush();
    assert.equal(scene.getTransformNodeByName('traffic-world'), null);
    assert.equal(loads, 1);
    view.setEnabled(true); view.update(); await flush();
    assert.equal(loads, 1);
    view.handleSnapshot([state('world', 1)]); view.update(); await flush();
    assert.equal(loads, 2);
  } finally { view.dispose(); scene.dispose(); engine.dispose(); }
});
