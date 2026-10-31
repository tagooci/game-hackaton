import assert from 'node:assert/strict';
import { test } from 'node:test';
import { NullEngine } from '@babylonjs/core/Engines/nullEngine.js';
import { TransformNode } from '@babylonjs/core/Meshes/transformNode.js';
import { Scene } from '@babylonjs/core/scene.js';
import { createRemotePlayers } from '../src/players/remotePlayers.ts';

const other = { id: 'p2', name: 'Bob', zone: 'world', x: 0, z: 2, heading: 0 };
const welcome = { type: 'welcome', playerId: 'p1', v: 2, inputHz: 20 };
const snapshot = { type: 'snapshot', tick: 0, players: [other] };

function setup(t) {
  const engine = new NullEngine();
  const scene = new Scene(engine);
  // Проверяем обработку snapshot отдельно от загрузки GLB в браузере.
  const remote = createRemotePlayers(scene, (scene, _length, name) => {
    const root = new TransformNode(name, scene);
    return {
      root,
      setPose: pose => { root.position.set(pose.x, 0, pose.z); root.rotation.y = pose.heading; },
      dispose: () => root.dispose(),
    };
  });
  t.after(() => { remote.dispose(); scene.dispose(); engine.dispose(); });
  return { scene, remote };
}

test('full snapshots create cars without duplicates and hide own player', t => {
  const { scene, remote } = setup(t);
  remote.handleMessage(welcome, 0);
  remote.handleMessage(snapshot, 0);
  remote.handleMessage({ ...snapshot, tick: 1, players: [other, {...other, id: 'p1'}] }, 0);
  assert.equal(scene.transformNodes.length, 1);
  assert.equal(scene.getTransformNodeByName('player-p1'), null);
  assert.equal(scene.getTransformNodeByName('player-p2').metadata.name, 'Bob');
  assert.equal(scene.getTransformNodeByName('player-p2').position.y, 0);
});

test('snapshot interpolates at 100 ms delay and rotates across pi by the short path', t => {
  const { scene, remote } = setup(t);
  remote.handleMessage(welcome, 0);
  remote.handleMessage(snapshot, 0);
  remote.handleMessage({ type: 'snapshot', tick: 1, players: [{ ...other, x: 1, heading: 3.1 }] }, 100);
  remote.handleMessage({ type: 'snapshot', tick: 2, players: [{ ...other, x: 3, heading: -3.1 }] }, 150);
  remote.update(225);
  const mesh = scene.getTransformNodeByName('player-p2');
  assert.equal(mesh.position.x, 2);
  assert.ok(Math.abs(mesh.rotation.y - Math.PI) < 1e-8);
  remote.handleMessage({ type: 'snapshot', tick: 1, players: [{ ...other, x: 100 }] }, 250);
  remote.update(400);
  assert.equal(mesh.position.x, 3);
});

test('full snapshots remove missing cars; transitions and disconnect clear interpolation', t => {
  const { scene, remote } = setup(t);
  remote.handleMessage(welcome, 0);
  remote.handleMessage(snapshot, 0);
  remote.handleMessage({ type: 'snapshot', tick: 1, players: [] }, 100);
  assert.equal(scene.transformNodes.length, 0);
  assert.equal(scene.transformNodes.length, 0);
  remote.handleMessage({...snapshot, tick: 2}, 200);
  remote.clear();
  assert.equal(scene.transformNodes.length, 0);
  remote.handleMessage(welcome, 300);
  remote.handleMessage(snapshot, 300);
  assert.equal(scene.transformNodes.length, 1);
  remote.handleMessage({ type: 'scene_prepare' }, 400);
  assert.equal(scene.transformNodes.length, 0);
});
