import assert from 'node:assert/strict';
import { test } from 'node:test';
import { NullEngine } from '@babylonjs/core/Engines/nullEngine.js';
import { Scene } from '@babylonjs/core/scene.js';
import { createRemotePlayers } from '../src/players/remotePlayers.ts';

const other = { id: 'p2', name: 'Bob', zone: 'world', x: 0, z: 2, heading: 0 };
const welcome = { type: 'welcome', id: 'p1', zone: 'world', x: 0, z: 0, heading: 0, players: [other] };

function setup(t) {
  const engine = new NullEngine();
  const scene = new Scene(engine);
  const remote = createRemotePlayers(scene);
  t.after(() => { remote.dispose(); scene.dispose(); engine.dispose(); });
  return { scene, remote };
}

test('welcome creates other player, joined is not duplicated, own player stays hidden', t => {
  const { scene, remote } = setup(t);
  remote.handleMessage(welcome, 0);
  remote.handleMessage({ type: 'player_joined', ...other }, 0);
  remote.handleMessage({ type: 'player_joined', ...other, id: 'p1' }, 0);
  assert.equal(scene.meshes.length, 2); // Capsule and its front marker.
  assert.equal(scene.getMeshByName('player-p1'), null);
  assert.equal(scene.getMeshByName('player-p2').metadata.name, 'Bob');
  assert.equal(scene.getMeshByName('player-p2').position.y, 0.85);
});

test('snapshot interpolates at 100 ms delay and rotates across pi by the short path', t => {
  const { scene, remote } = setup(t);
  remote.handleMessage(welcome, 0);
  remote.handleMessage({ type: 'snapshot', tick: 1, players: [{ ...other, x: 1, heading: 3.1 }] }, 100);
  remote.handleMessage({ type: 'snapshot', tick: 2, players: [{ ...other, x: 3, heading: -3.1 }] }, 150);
  remote.update(225);
  const mesh = scene.getMeshByName('player-p2');
  assert.equal(mesh.position.x, 2);
  assert.ok(Math.abs(mesh.rotation.y - Math.PI) < 1e-8);
  remote.handleMessage({ type: 'snapshot', tick: 1, players: [{ ...other, x: 100 }] }, 250);
  remote.update(400);
  assert.equal(mesh.position.x, 3);
});

test('missing snapshots do not remove player; leave, disconnect and new welcome clear meshes', t => {
  const { scene, remote } = setup(t);
  remote.handleMessage(welcome, 0);
  remote.handleMessage({ type: 'snapshot', tick: 1, players: [] }, 100);
  assert.equal(scene.meshes.length, 2);
  remote.handleMessage({ type: 'player_left', id: 'p2' }, 150);
  assert.equal(scene.meshes.length, 0);
  remote.handleMessage({ type: 'player_joined', ...other }, 200);
  remote.clear();
  assert.equal(scene.meshes.length, 0);
  remote.handleMessage(welcome, 300);
  assert.equal(scene.meshes.length, 2);
  remote.handleMessage({ ...welcome, players: [] }, 400);
  assert.equal(scene.meshes.length, 0);
});
