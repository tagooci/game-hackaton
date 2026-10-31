import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createScenarioTransition } from '../src/scenarios/transition.ts';
import { createJunctionScene, createVehicle } from '../src/scenarios/junctionScene.ts';
import { NullEngine } from '@babylonjs/core/Engines/nullEngine.js';
import { readFileSync } from 'node:fs';

const prepare = epoch => ({ sceneId: `scenario:${epoch}`, epoch, plan: { revision: 1 } });

test('ready waits for loading; start requires matching epoch and server tick; finish locks input', async () => {
  const sent = [];
  let enabled = false;
  const adapter = createScenarioTransition({
    setControlsEnabled: value => { enabled = value; }, clearVehicles() {},
    async load() { return { dispose() {} }; }, send: message => sent.push(message),
  });
  await adapter.prepare(prepare(2));
  assert.deepEqual(sent, [{ type: 'scene_ready', sceneId: 'scenario:2', epoch: 2, revision: 1 }]);
  adapter.start({ sceneId: 'scenario:1', epoch: 1, startTick: 5 });
  adapter.tick('scenario:2', 2, 10);
  assert.equal(enabled, false);
  adapter.start({ sceneId: 'scenario:2', epoch: 2, startTick: 20 });
  adapter.tick('scenario:2', 2, 19);
  assert.equal(enabled, false);
  adapter.tick('scenario:2', 2, 20);
  assert.equal(enabled, true);
  adapter.finish();
  adapter.tick('scenario:2', 2, 21);
  assert.equal(enabled, false);
  adapter.dispose();
});

test('a late map load cannot replace a newer scene or acknowledge old epoch', async () => {
  const resolvers = [];
  const sent = [];
  const disposed = [];
  const adapter = createScenarioTransition({
    setControlsEnabled() {}, clearVehicles() {},
    load: message => new Promise(resolve => resolvers.push(() => resolve({ dispose: () => disposed.push(message.epoch) }))),
    send: message => sent.push(message),
  });
  const first = adapter.prepare(prepare(2));
  const second = adapter.prepare(prepare(3));
  resolvers[1]();
  await second;
  resolvers[0]();
  await first;
  assert.deepEqual(disposed, [2]);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].epoch, 3);
  await adapter.prepare(prepare(3));
  assert.equal(sent.length, 1);
  adapter.dispose();
  assert.deepEqual(disposed, [2, 3]);
});

test('load failure reports scene_failed and never unlocks controls', async () => {
  const sent = [];
  const adapter = createScenarioTransition({
    setControlsEnabled: value => assert.equal(value, false), clearVehicles() {},
    async load() { throw new Error('bad asset'); }, send: message => sent.push(message),
  });
  await adapter.prepare(prepare(2));
  assert.equal(sent[0].type, 'scene_failed');
  adapter.start({ sceneId: 'scenario:2', epoch: 2, startTick: 0 });
  adapter.tick('scenario:2', 2, 1);
  adapter.dispose();
});

test('map and replaceable models build from the shared data and release all resources', () => {
  const definition = JSON.parse(readFileSync(new URL('../public/scenarios/priority-01.json', import.meta.url), 'utf8'));
  const engine = new NullEngine();
  const scene = createJunctionScene(engine, definition);
  for (const role of definition.roles) {
    const mesh = createVehicle(scene, role, role.roleId);
    assert.equal(mesh.position.x, role.spawn.x);
    assert.equal(mesh.position.z, role.spawn.z);
    assert.equal(mesh.position.y, 0);
    assert.equal(mesh.rotation.y, role.spawn.heading);
    assert.ok(mesh.getChildMeshes().length > 0);
  }
  assert.ok(scene.getMeshByName('stop-line-0'));
  scene.dispose();
  assert.equal(engine.scenes.length, 0);
  engine.dispose();
});
