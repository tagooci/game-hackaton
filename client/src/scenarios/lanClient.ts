import '../style.css';
import { Engine } from '@babylonjs/core/Engines/engine';
import { FreeCamera } from '@babylonjs/core/Cameras/freeCamera';
import { Vector3 } from '@babylonjs/core/Maths/math.vector';
import type { Scene } from '@babylonjs/core/scene';
import type { Mesh } from '@babylonjs/core/Meshes/mesh';
import { createJunctionScene, createVehicle } from './junctionScene';
import { loadJunction } from './definition';
import type { JunctionDefinition } from './definition';

interface VehicleState {
  id: string; name: string; roleId: string; vehicleType: string;
  x: number; z: number; heading: number; speed: number; finished: boolean;
}
interface LabState {
  type: 'lab_snapshot'; tick: number; playerId: string; sceneId: string;
  phase: string; players: VehicleState[]; queued: boolean; waiting: number; busy: boolean;
  countdown: number; remaining: number;
  result: null | { status: string; reason: string; violations: { text: string }[] };
  returned: null | { x: number; z: number; heading: number };
}

const panel = document.createElement('section');
panel.className = 'scenario-panel';
panel.innerHTML = '<h1>Перекрёсток · LAN</h1><p class="lab-status">Загрузка…</p><form><label>Имя <input maxlength="24" required value="Игрок"></label><button>Подключиться</button></form><p class="lab-roster"></p><button class="lab-queue" disabled>Enter — зайти в сценарий</button><p>W/S — газ и задний ход · A/D — руль · Space — тормоз</p><p class="lab-result" role="status"></p><small>Тестовая комната на 2–3 игроков. Большой мир ещё не подключён. Проверка приоритета упрощена.</small>';
document.body.append(panel);
const status = panel.querySelector<HTMLElement>('.lab-status')!;
const roster = panel.querySelector<HTMLElement>('.lab-roster')!;
const result = panel.querySelector<HTMLElement>('.lab-result')!;
const queue = panel.querySelector<HTMLButtonElement>('.lab-queue')!;
const form = panel.querySelector('form')!;
const input = panel.querySelector('input')!;
const button = form.querySelector('button')!;
button.disabled = true;
input.value = (new URLSearchParams(location.search).get('name') || 'Игрок').slice(0, 24);
const abort = new AbortController();
const canvas = document.createElement('canvas');
canvas.tabIndex = 0;
document.querySelector('#app')!.append(canvas);
const engine = new Engine(canvas, true);
let definition: JunctionDefinition;
let scene: Scene | undefined;
let camera: FreeCamera;
let socket: WebSocket | undefined;
let latest: LabState | undefined;
let sceneId: string | undefined;
let seq = 0;
let generation = 0;
let retry: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
let connected = false;
let focused = document.hasFocus();
const keys = new Set<string>();
const vehicles = new Map<string, { mesh: Mesh; target: VehicleState; type: string }>();
const labels: Record<string, string> = { car: 'Легковая', truck: 'КамАЗ', tram: 'Трамвай' };
const reasons: Record<string, string> = {
  collision: 'Столкновение', completed: 'Проезд завершён без нарушений',
  priority_violation: 'Нарушен приоритет', time_limit: 'Время истекло',
  participant_disconnected: 'Участник отключился — сценарий отменён',
  loading_timeout: 'Не все участники загрузили сцену', loading_failed: 'Ошибка загрузки сцены',
};

function send(message: object) {
  if (socket?.readyState === WebSocket.OPEN && socket.bufferedAmount < 16384) socket.send(JSON.stringify(message));
}

function controls(brake = false) {
  brake = brake || !focused || document.hidden;
  const state = latest;
  const own = state?.players.find(p => p.id === state.playerId);
  if (!connected || state?.phase !== 'running' || own?.finished) return;
  send({ type: 'lab_input', sceneId: state.sceneId, seq: ++seq,
    throttle: brake ? 0 : Number(keys.has('KeyW')) - Number(keys.has('KeyS')),
    steering: brake ? 0 : Number(keys.has('KeyD')) - Number(keys.has('KeyA')),
    brake: brake || keys.has('Space') ? 1 : 0 });
}

function changeScene(state: LabState) {
  const currentGeneration = ++generation;
  scene?.dispose();
  vehicles.clear();
  keys.clear();
  seq = 0;
  sceneId = state.sceneId;
  scene = createJunctionScene(engine, definition);
  camera = new FreeCamera('lan-hood-camera', new Vector3(25, 28, -35), scene);
  camera.inputs.clear();
  camera.minZ = .1;
  camera.setTarget(Vector3.Zero());
  const loadedScene = scene;
  // WebSocket readiness is acknowledged only after all scene resources are ready.
  if (state.phase === 'loading') {
    void loadedScene.whenReadyAsync().then(() => {
      if (!disposed && currentGeneration === generation && connected) {
        send({ type: 'lab_ready', sceneId: state.sceneId });
      }
    }).catch(() => {
      if (currentGeneration === generation) send({ type: 'lab_load_failed', sceneId: state.sceneId });
    });
  }
}

function accept(state: LabState) {
  if (latest?.sceneId === state.sceneId && state.tick < latest.tick) return;
  latest = state;
  if (state.sceneId !== sceneId) changeScene(state);
  const visible = new Set(state.players.map(p => p.id));
  for (const [id, vehicle] of vehicles) {
    if (!visible.has(id)) {
      vehicle.mesh.dispose(false, true);
      vehicles.delete(id);
    }
  }
  for (const p of state.players) {
    if (![p.x, p.z, p.heading, p.speed].every(Number.isFinite)) continue;
    let vehicle = vehicles.get(p.id);
    if (!vehicle || vehicle.type !== p.vehicleType) {
      vehicle?.mesh.dispose(false, true);
      const role = definition.roles.find(r => r.vehicleType === p.vehicleType);
      if (!role) continue;
      const mesh = createVehicle(scene!, role, `lan-${p.id}`);
      mesh.position.set(p.x, 0, p.z);
      mesh.rotation.y = p.heading;
      vehicle = { mesh, target: p, type: p.vehicleType };
      vehicles.set(p.id, vehicle);
    }
    vehicle.target = p;
  }
  roster.textContent = state.players.map(p => `${p.name}: ${labels[p.vehicleType] || p.vehicleType}${p.id === state.playerId ? ' (вы)' : ''}${p.finished ? ' — финиш' : ''}`).join(' · ');
  const own = state.players.find(p => p.id === state.playerId);
  const statuses: Record<string, string> = {
    lobby: state.busy ? 'Другие игроки уже проходят сценарий. Дождитесь завершения.' : state.queued ? `Ожидание: ${state.waiting}/3${state.waiting >= 2 ? ` · сбор группы ${state.countdown} с` : ' · нужен второй игрок'}` : 'Подключено. Нажмите Enter для участия.',
    loading: 'Загружаем сцену и ждём готовности всех…',
    countdown: `Старт через ${state.countdown}…`,
    running: `${own?.finished ? 'Вы завершили проезд. Ждём остальных.' : 'Проезд'} · осталось ${state.remaining} с`,
    finished: 'Сценарий завершён · возврат в тестовое лобби через 5 с',
    cancelled: 'Сценарий отменён · возврат в тестовое лобби через 5 с',
  };
  status.textContent = statuses[state.phase] || state.phase;
  queue.disabled = state.phase !== 'lobby' || state.busy;
  queue.textContent = state.queued ? 'Покинуть очередь' : 'Enter — зайти в сценарий';
  result.textContent = state.result
    ? `${reasons[state.result.reason] || state.result.reason}${state.result.violations.length ? ': ' + state.result.violations.map(v => v.text).join('; ') : ''}`
    : '';
  if (state.returned) result.textContent += ` · Точка возврата: ${state.returned.x.toFixed(1)}, ${state.returned.z.toFixed(1)}. Это тестовое лобби, не большая карта.`;
}

function connect() {
  if (disposed) return;
  clearTimeout(retry);
  socket?.close();
  connected = false;
  latest = undefined;
  sceneId = undefined;
  generation++;
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/lab/ws`);
  socket = ws;
  status.textContent = 'Подключение…';
  button.disabled = true;
  input.disabled = true;
  ws.onopen = () => send({ type: 'lab_join', name: input.value.trim() || 'Игрок' });
  ws.onmessage = event => {
    if (socket !== ws) return;
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message?.type === 'lab_welcome') connected = true;
    if (message?.type === 'lab_error') result.textContent = message.text;
    if (message?.type === 'lab_snapshot' && Array.isArray(message.players)) accept(message);
  };
  ws.onclose = event => {
    if (socket !== ws || disposed) return;
    connected = false;
    keys.clear();
    generation++;
    scene?.dispose();
    scene = undefined;
    vehicles.clear();
    queue.disabled = true;
    button.disabled = false;
    input.disabled = false;
    status.textContent = event.code === 1008 ? 'Вход отклонён: возможно, комната заполнена.' : 'Соединение потеряно. Повтор через 3 секунды…';
    if (event.code !== 1008) retry = setTimeout(connect, 3000);
  };
  ws.onerror = () => ws.close();
}

function toggleQueue() {
  if (latest?.phase === 'lobby' && !latest.busy) send({ type: latest.queued ? 'lab_leave_queue' : 'lab_queue' });
}
form.addEventListener('submit', event => { event.preventDefault(); connect(); }, { signal: abort.signal });
queue.addEventListener('click', toggleQueue, { signal: abort.signal });
window.addEventListener('keydown', event => {
  if (event.target instanceof HTMLInputElement || event.repeat) return;
  if (event.code === 'Enter') { event.preventDefault(); toggleQueue(); }
  if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'Space'].includes(event.code)) { event.preventDefault(); keys.add(event.code); }
}, { signal: abort.signal });
window.addEventListener('keyup', event => keys.delete(event.code), { signal: abort.signal });
function release() { focused = false; keys.clear(); controls(true); }
window.addEventListener('blur', release, { signal: abort.signal });
window.addEventListener('focus', () => { focused = true; }, { signal: abort.signal });
document.addEventListener('visibilitychange', () => { if (document.hidden) release(); }, { signal: abort.signal });
window.addEventListener('resize', () => engine.resize(), { signal: abort.signal });
const timer = setInterval(() => controls(), 50);

try {
  definition = await loadJunction(abort.signal);
  button.disabled = false;
  status.textContent = 'Введите имя и подключитесь';
  engine.runRenderLoop(() => {
    if (!scene) return;
    const t = 1 - Math.exp(-engine.getDeltaTime() / 65);
    for (const { mesh, target } of vehicles.values()) {
      mesh.position.x += (target.x - mesh.position.x) * t;
      mesh.position.z += (target.z - mesh.position.z) * t;
      const delta = Math.atan2(Math.sin(target.heading - mesh.rotation.y), Math.cos(target.heading - mesh.rotation.y));
      mesh.rotation.y += delta * t;
    }
    const own = latest && vehicles.get(latest.playerId);
    if (own && latest?.phase !== 'lobby') {
      const role = definition.roles.find(r => r.vehicleType === own.type)!;
      const heading = own.mesh.rotation.y;
      const offset = role.length / 2 - .65;
      camera.position.set(own.mesh.position.x + Math.sin(heading) * offset,
        role.vehicleType === 'car' ? 1.35 : 2.65,
        own.mesh.position.z + Math.cos(heading) * offset);
      camera.rotation.set(.04, heading, 0);
    }
    scene.render();
  });
  // A URL name is convenient for opening two local test tabs.
  if (new URLSearchParams(location.search).has('name')) connect();
} catch (error) {
  status.textContent = `Ошибка загрузки карты: ${String(error)}`;
  button.disabled = true;
}

function dispose() {
  disposed = true;
  generation++;
  abort.abort();
  clearTimeout(retry);
  clearInterval(timer);
  socket?.close();
  scene?.dispose();
  engine.dispose();
  panel.remove();
  canvas.remove();
}
import.meta.hot?.dispose(dispose);
window.addEventListener('pagehide', dispose, { once: true, signal: abort.signal });
