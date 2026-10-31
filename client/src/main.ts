import './style.css';
import { api, ApiError, showAuth } from './auth/session';
import type { Account } from './auth/session';

import { Engine } from '@babylonjs/core/Engines/engine';
import { Scene } from '@babylonjs/core/scene';
import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera';
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight';
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder';
import { Vector3 } from '@babylonjs/core/Maths/math.vector';
import { Color3 } from '@babylonjs/core/Maths/math.color';
import type { VehiclePose } from './vehicle/vehicleView';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial';
import { startStateSender } from './network/stateSender';
import { createRemotePlayers } from './players/remotePlayers';
import { createVehicleView } from './vehicle/vehicleView';
import { createVehicleControls } from './vehicle/controls';

const host = document.querySelector<HTMLDivElement>('#app')!;
let stopScreen = () => {};
let disposed = false;

function authScreen(error = ''): void {
  stopScreen();
  stopScreen = showAuth(host, enterGame, error);
}

async function enterGame(account: Account): Promise<void> {
  await api('content/bootstrap');
  if (disposed) return;
  stopScreen();
  host.replaceChildren();
  stopScreen = startGame(account);
}

function startGame(account: Account): () => void {
  const events = new AbortController();
  const eventOptions = { signal: events.signal };

  // Создаём область, в которой Babylon.js будет рисовать.
  const canvas = document.createElement('canvas');
  host.append(canvas);

  // Движок управляет отрисовкой.
  const engine = new Engine(canvas, true);

  // Сцена содержит камеру, свет и объекты.
  const scene = new Scene(engine);

  // Длина модели в метрах; пропорции сохраняются при загрузке.
  const vehicle = createVehicleView(scene, 4.4);
  vehicle.setPose({ x: 0, z: 0, heading: 0 });

  // Камера наблюдает за машиной и не управляет её положением.
  const camera = new ArcRotateCamera(
    'camera',
    -Math.PI / 2,
    Math.PI / 3,
    10,
    Vector3.Zero(),
    scene,
  );
  camera.lockedTarget = vehicle.body;
  camera.lowerRadiusLimit = 5;
  camera.upperRadiusLimit = 20;
  camera.lowerBetaLimit = 0.2;
  camera.upperBetaLimit = Math.PI / 2 - 0.05;
  camera.panningSensibility = 0;
  camera.inputs.removeByType('ArcRotateCameraKeyboardMoveInput');
  camera.attachControl(canvas, false);
  scene.activeCamera = camera;
  canvas.tabIndex = 0;
  const controls = createVehicleControls(canvas);
  let ownId = '';
  let targetPose: VehiclePose = vehicle.getPose();

  // Освещение сверху.
  new HemisphericLight('light', new Vector3(0, 1, 0), scene);

  // Площадка 100 × 100 м; шаг сетки — 1 м.
  const ground = MeshBuilder.CreateGround(
    'ground',
    { width: 100, height: 100 },
    scene,
  );

  const groundMaterial = new StandardMaterial('ground-material', scene);
  groundMaterial.diffuseColor = new Color3(0.3, 0.32, 0.35);
  ground.material = groundMaterial;
  const lines: Vector3[][] = [];
  for (let i = -50; i <= 50; i++) {
    lines.push([new Vector3(i, 0.01, -50), new Vector3(i, 0.01, 50)]);
    lines.push([new Vector3(-50, 0.01, i), new Vector3(50, 0.01, i)]);
  }
  const grid = MeshBuilder.CreateLineSystem('ground-grid', { lines }, scene);
  grid.color = new Color3(0.5, 0.53, 0.57);

  const overlay = document.createElement('div');
  overlay.className = 'loading-screen';
  overlay.textContent = 'Подключение…';
  canvas.addEventListener('click', () => {
    if (!overlay.hidden || document.pointerLockElement === canvas) return;
    canvas.requestPointerLock().catch(error => console.warn('Не удалось захватить курсор:', error));
  }, eventOptions);
  const logout = document.createElement('button');
  logout.className = 'logout';
  logout.textContent = `Выйти (${account.name})`;
  host.append(overlay, logout);
  logout.onclick = async () => {
    logout.disabled = true;
    try { await api('logout', {}); authScreen(); }
    catch { overlay.hidden = false; overlay.textContent = 'Не удалось выйти. Попробуйте ещё раз.'; logout.disabled = false; }
  };
  const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const serverUrl = `${wsProtocol}//${location.host}/ws/v2`;
  const remotePlayers = createRemotePlayers(scene);
  const stopStateSender = startStateSender(serverUrl, {
    getControls: controls.getControls,
    prepareScene: async message => {
      const expected = new Set(['car-kit/sedan.glb', 'car-kit/Textures/colormap.png']);
      if (message.plan.resources.length !== expected.size || message.plan.resources.some(r => !expected.has(r.id))) {
        throw new Error('Неподдерживаемый план сцены');
      }
      overlay.textContent = 'Загрузка машины…';
      await vehicle.ready;
      overlay.textContent = 'Подготовка сцены…';
      await scene.whenReadyAsync();
    },
    onStatus: text => { overlay.hidden = !text; overlay.textContent = text; },
    onSessionEnd: code => authScreen(code === 4001 ? 'Аккаунт уже подключён в другом окне' : 'Войдите в аккаунт снова'),
    onMessage: message => {
      if (message.type === 'welcome') ownId = message.playerId;
      if (message.type === 'scene_prepare') {
        controls.clear();
        vehicle.setPose(message.spawn);
        targetPose = message.spawn;
      }
      if (message.type === 'snapshot') {
        const own = message.players.find(player => player.id === ownId);
        if (own) targetPose = own;
      }
      remotePlayers.handleMessage(message);
    },
    onDisconnect: () => {
      remotePlayers.clear(); controls.clear(); targetPose = vehicle.getPose();
    },
  });

  // На каждом кадре рисуем сцену из положения камеры.
  engine.runRenderLoop(() => {
    // Сглаживание отрисовки, не расчёт физики: движемся только к позиции сервера.
    const pose = vehicle.getPose();
    const blend = 1 - Math.exp(-20 * Math.min(engine.getDeltaTime() / 1000, 0.1));
    const angle = Math.atan2(Math.sin(targetPose.heading - pose.heading), Math.cos(targetPose.heading - pose.heading));
    vehicle.setPose({
      x: pose.x + (targetPose.x - pose.x) * blend,
      z: pose.z + (targetPose.z - pose.z) * blend,
      heading: pose.heading + angle * blend,
      wheelAngle: (pose.wheelAngle ?? 0) + ((targetPose.wheelAngle ?? 0) - (pose.wheelAngle ?? 0)) * blend,
      color: targetPose.color,
    });
    remotePlayers.update();
    scene.render();
  });

  // Подстраиваем размер изображения при изменении окна.
  window.addEventListener('resize', () => {
    engine.resize();
  }, eventOptions);

  function dispose(): void {
    if (document.pointerLockElement === canvas) document.exitPointerLock();
    stopStateSender();
    controls.dispose();
    events.abort();
    engine.stopRenderLoop();
    remotePlayers.dispose();
    vehicle.dispose();
    scene.dispose();
    engine.dispose();
    canvas.remove();
  }

  return () => { dispose(); overlay.remove(); logout.remove(); };
}

host.textContent = 'Проверка сессии…';
api<Account>('me').then(enterGame).catch(error => {
  if (!disposed) authScreen(error instanceof ApiError && error.status === 401 ? '' : 'Не удалось подключиться к серверу');
});
function disposeApplication(): void { disposed = true; stopScreen(); }
import.meta.hot?.dispose(disposeApplication);
window.addEventListener('pagehide', event => { if (!event.persisted) disposeApplication(); });
