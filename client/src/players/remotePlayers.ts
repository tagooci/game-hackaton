import { createVehicleView, VEHICLE_LENGTH } from '../vehicle/vehicleView.ts';
import type { Scene } from '@babylonjs/core/scene.js';
import type { PlayerSnapshot, ServerMessage } from '../network/protocol';

const INTERPOLATION_DELAY_MS = 100;
const MAX_SAMPLES = 8;

interface Sample extends PlayerSnapshot {
  time: number;
}

/** Rendering only: the network module supplies events, Babylon renders the meshes. */
export function createRemotePlayers(scene: Scene, createView = createVehicleView) {
  const players = new Map<string, { vehicle: ReturnType<typeof createVehicleView>; samples: Sample[] }>();
  let ownId: string | undefined;
  let lastTick = -1;

  function addPlayer(player: PlayerSnapshot, now: number): void {
    if (player.id === ownId || players.has(player.id)) return;
    const vehicle = createView(scene, VEHICLE_LENGTH, `player-${player.id}`);
    vehicle.setPose(player);
    vehicle.root.metadata = { playerId: player.id, name: player.name };
    players.set(player.id, { vehicle, samples: [{ ...player, time: now }] });
  }

  function clear(): void {
    for (const { vehicle } of players.values()) vehicle.dispose();
    players.clear();
    ownId = undefined;
    lastTick = -1;
  }

  function handleMessage(message: ServerMessage, now = performance.now()): void {
    switch (message.type) {
      case 'welcome':
        clear();
        ownId = message.playerId;
        break;
      case 'scene_prepare': {
        const id = ownId;
        clear();
        ownId = id;
        break;
      }
      case 'snapshot':
        if (!ownId || message.tick <= lastTick) return;
        lastTick = message.tick;
        const visible = new Set(message.players.map(player => player.id));
        for (const [id, player] of players) {
          if (!visible.has(id)) { player.vehicle.dispose(); players.delete(id); }
        }
        for (const state of message.players) {
          addPlayer(state, now);
          const player = players.get(state.id);
          if (!player) continue; // Своя машина отображается отдельно.
          player.samples.push({ ...state, time: now });
          if (player.samples.length > MAX_SAMPLES) player.samples.shift();
        }
        break;
    }
  }

  function update(now = performance.now()): void {
    const renderTime = now - INTERPOLATION_DELAY_MS;
    for (const { vehicle, samples } of players.values()) {
      while (samples.length > 2 && samples[1].time <= renderTime) samples.shift();
      const from = samples[0];
      const to = samples[1] ?? from;
      const duration = to.time - from.time;
      const t = duration > 0 ? Math.max(0, Math.min(1, (renderTime - from.time) / duration)) : 1;
      const angle = Math.atan2(Math.sin(to.heading - from.heading), Math.cos(to.heading - from.heading));
      vehicle.setPose({
        x: from.x + (to.x - from.x) * t,
        z: from.z + (to.z - from.z) * t,
        heading: from.heading + angle * t,
        y: (from.y ?? 0) + ((to.y ?? 0) - (from.y ?? 0)) * t,
        pitch: (from.pitch ?? 0) + ((to.pitch ?? 0) - (from.pitch ?? 0)) * t,
        wheelAngle: (from.wheelAngle ?? 0) + ((to.wheelAngle ?? 0) - (from.wheelAngle ?? 0)) * t,
        color: to.color,
      });
    }
  }

  function dispose(): void {
    clear();
  }

  return { handleMessage, update, clear, dispose };
}
