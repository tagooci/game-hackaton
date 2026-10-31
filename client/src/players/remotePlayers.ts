import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder.js';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial.js';
import { Color3 } from '@babylonjs/core/Maths/math.color.js';
import type { Mesh } from '@babylonjs/core/Meshes/mesh.js';
import type { Scene } from '@babylonjs/core/scene.js';
import type { PlayerInfo, PlayerSnapshot, ServerMessage } from '../network/protocol';

const HEIGHT = 1.7;
const INTERPOLATION_DELAY_MS = 100;
const MAX_SAMPLES = 8;

interface Sample extends PlayerSnapshot {
  time: number;
}

/** Rendering only: the network module supplies events, Babylon renders the meshes. */
export function createRemotePlayers(scene: Scene) {
  const players = new Map<string, { mesh: Mesh; samples: Sample[] }>();
  const material = new StandardMaterial('remote-player-material', scene);
  material.diffuseColor = Color3.FromHexString('#329b85');
  const markerMaterial = new StandardMaterial('remote-player-front-material', scene);
  markerMaterial.diffuseColor = Color3.FromHexString('#f2bd66');
  let ownId: string | undefined;
  let lastTick = -1;

  function addPlayer(player: PlayerInfo, now: number): void {
    if (player.id === ownId || players.has(player.id)) return;
    const mesh = MeshBuilder.CreateCapsule(`player-${player.id}`, { height: HEIGHT, radius: 0.3, tessellation: 12 }, scene);
    mesh.material = material;
    mesh.position.set(player.x, HEIGHT / 2, player.z);
    mesh.rotation.y = player.heading;
    mesh.metadata = { playerId: player.id, name: player.name, zone: player.zone };
    // A front marker makes heading visible even though the capsule is symmetrical.
    const marker = MeshBuilder.CreateBox(`player-front-${player.id}`, { size: 0.16 }, scene);
    marker.material = markerMaterial;
    marker.parent = mesh;
    marker.position.set(0, 0.45, 0.29);
    players.set(player.id, { mesh, samples: [{ ...player, time: now }] });
  }

  function clear(): void {
    for (const { mesh } of players.values()) mesh.dispose();
    players.clear();
    ownId = undefined;
    lastTick = -1;
  }

  function handleMessage(message: ServerMessage, now = performance.now()): void {
    switch (message.type) {
      case 'welcome':
        clear();
        ownId = message.id;
        for (const player of message.players) addPlayer(player, now);
        break;
      case 'player_joined':
        if (ownId) addPlayer(message, now);
        break;
      case 'snapshot':
        if (!ownId || message.tick <= lastTick) return;
        lastTick = message.tick;
        for (const state of message.players) {
          const player = players.get(state.id);
          if (!player) continue; // Own player and not-yet-announced IDs are ignored.
          player.samples.push({ ...state, time: now });
          if (player.samples.length > MAX_SAMPLES) player.samples.shift();
        }
        break;
      case 'player_left':
        players.get(message.id)?.mesh.dispose();
        players.delete(message.id);
        break;
    }
  }

  function update(now = performance.now()): void {
    const renderTime = now - INTERPOLATION_DELAY_MS;
    for (const { mesh, samples } of players.values()) {
      while (samples.length > 2 && samples[1].time <= renderTime) samples.shift();
      const from = samples[0];
      const to = samples[1] ?? from;
      const duration = to.time - from.time;
      const t = duration > 0 ? Math.max(0, Math.min(1, (renderTime - from.time) / duration)) : 1;
      mesh.position.set(from.x + (to.x - from.x) * t, HEIGHT / 2, from.z + (to.z - from.z) * t);
      const angle = Math.atan2(Math.sin(to.heading - from.heading), Math.cos(to.heading - from.heading));
      mesh.rotation.y = from.heading + angle * t;
    }
  }

  function dispose(): void {
    clear();
    material.dispose();
    markerMaterial.dispose();
  }

  return { handleMessage, update, clear, dispose };
}
