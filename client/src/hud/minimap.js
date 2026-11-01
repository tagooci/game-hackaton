import './minimap.css';
import map from '../assets/minimap/map.json';
import trackUrl from '../assets/minimap/track.webp?url';

export const VEHICLE_PIN_COLORS = ['#44ad7d', '#ffba4f', '#ff8c44', '#ec6346', '#607acd'];
const SIZE = 320;
const b = map.bounds;
const scaleX = SIZE / (b.maxX - b.minX);
const scaleZ = SIZE / (b.maxZ - b.minZ);

export function minimapPosition(x, z) {
  return [(x - b.minX) * scaleX / SIZE * 1000, (b.maxZ - z) * scaleZ / SIZE * 1000];
}

/** Canvas overlay, updated directly from server snapshots, never from the 3D render loop.
 * @param {HTMLElement} host
 */
export function createMinimap(host) {
  const panel = document.createElement('aside');
  panel.className = 'minimap';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Миникарта трассы и позиции игроков');
  panel.innerHTML = `<img class="minimap__background" src="${trackUrl}" alt="Трасса с домами и разметкой" decoding="async" draggable="false"><canvas class="minimap__pins" width="${SIZE}" height="${SIZE}" aria-label="Позиции игроков"></canvas>`;
  host.append(panel);
  const context = panel.querySelector('canvas').getContext('2d', { alpha: true });
  let ready = false;
  let disposed = false;
  let lastUpdate = -Infinity;
  let count = -1;
  let ownIndex = -1;
  // Reuse flat buffers; no per-tick objects, arrays, SVG nodes or DOM mutations.
  let state = new Float64Array(32 * 4);

  function setReady(value) {
    ready = value;
    lastUpdate = -Infinity;
    count = -1;
    panel.hidden = !value;
    if (!value) context.clearRect(0, 0, SIZE, SIZE);
  }

  /** @param {string} ownId @param {import('../network/protocol').PlayerSnapshot[]} players */
  function update(ownId, players) {
    if (!ready || disposed || document.hidden || !ownId) return;
    const now = performance.now();
    if (now - lastUpdate < 95) return;
    lastUpdate = now;
    const length = players.length;
    if (length * 4 > state.length) state = new Float64Array(length * 8);
    let changed = length !== count;
    let nextOwnIndex = -1;
    for (let i = 0; i < length; i++) {
      const player = players[i];
      const offset = i * 4;
      // Quantize to half a canvas pixel; sub-pixel noise does not trigger painting.
      const x = Math.round((player.x - b.minX) * scaleX * 2) / 2;
      const y = Math.round((b.maxZ - player.z) * scaleZ * 2) / 2;
      const color = player.color ?? 3;
      const heading = player.id === ownId ? Math.round(player.heading * 30) / 30 : 0;
      if (player.id === ownId) nextOwnIndex = i;
      if (state[offset] !== x || state[offset + 1] !== y || state[offset + 2] !== color || state[offset + 3] !== heading) changed = true;
      state[offset] = x; state[offset + 1] = y; state[offset + 2] = color; state[offset + 3] = heading;
    }
    if (ownIndex !== nextOwnIndex) changed = true;
    if (!changed) return;
    count = length;
    ownIndex = nextOwnIndex;
    context.clearRect(0, 0, SIZE, SIZE);
    context.lineWidth = 2;
    context.strokeStyle = '#fff';
    for (let i = 0; i < length; i++) if (i !== ownIndex) dot(i, false);
    if (ownIndex !== -1) dot(ownIndex, true);
  }

  function dot(index, own) {
    const offset = index * 4;
    const x = state[offset], y = state[offset + 1];
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    if (own) {
      context.strokeStyle = '#292b2b';
      context.beginPath(); context.arc(x, y, 8.5, 0, Math.PI * 2); context.stroke();
      const angle = state[offset + 3];
      const sin = Math.sin(angle), cos = Math.cos(angle);
      context.fillStyle = '#292b2b';
      context.beginPath();
      context.moveTo(x + sin * 16, y - cos * 16);
      context.lineTo(x + sin * 11 - cos * 3, y - cos * 11 - sin * 3);
      context.lineTo(x + sin * 11 + cos * 3, y - cos * 11 + sin * 3);
      context.closePath(); context.fill();
      context.strokeStyle = '#fff';
    }
    context.fillStyle = VEHICLE_PIN_COLORS[state[offset + 2]] ?? VEHICLE_PIN_COLORS[3];
    context.beginPath(); context.arc(x, y, own ? 5.8 : 4.8, 0, Math.PI * 2);
    context.fill(); context.stroke();
  }

  return { setReady, update, dispose() { disposed = true; state = new Float64Array(0); panel.remove(); } };
}
