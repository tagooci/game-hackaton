import './style.css';

import { Engine } from '@babylonjs/core/Engines/engine';
import { Scene } from '@babylonjs/core/scene';
import { UniversalCamera } from '@babylonjs/core/Cameras/universalCamera';
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight';
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder';
import { Vector3 } from '@babylonjs/core/Maths/math.vector';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial';
import { startStateSender } from './network/stateSender';
import { createRemotePlayers } from './players/remotePlayers';

const EYE_HEIGHT = 1.7;
const events = new AbortController();
const eventOptions = { signal: events.signal };

// Создаём область, в которой Babylon.js будет рисовать.
const canvas = document.createElement('canvas');
document.querySelector<HTMLDivElement>('#app')!.append(canvas);

// Движок управляет отрисовкой.
const engine = new Engine(canvas, true);

// Сцена содержит камеру, свет и объекты.
const scene = new Scene(engine);

// Камера от первого лица, на высоте глаз.
const camera = new UniversalCamera(
  'camera',
  new Vector3(0, EYE_HEIGHT, -4),
  scene,
);

camera.rotation.set(0, 0, 0);
scene.activeCamera = camera;

// Используем встроенное управление Babylon.js.
camera.keysUp = [87];    // W
camera.keysDown = [83];  // S
camera.keysLeft = [65];  // A
camera.keysRight = [68]; // D
camera.keysUpward = [];
camera.keysDownward = [];
camera.speed = 0.3;
camera.inertia = 0;
camera.angularSensibility = 2000;

canvas.tabIndex = 0;

canvas.addEventListener('click', async () => {
  if (document.pointerLockElement === canvas) return;
  canvas.focus();
  try {
    await canvas.requestPointerLock();
  } catch (error) {
    console.warn('Не удалось захватить курсор. Нажми на сцену ещё раз.', error);
  }
}, eventOptions);

// Управление активно только после клика; Esc освобождает курсор.
document.addEventListener('pointerlockchange', () => {
  if (document.pointerLockElement === canvas) {
    camera.attachControl(canvas, false);
  } else {
    camera.detachControl();
    camera.cameraDirection.setAll(0);
    camera.cameraRotation.setAll(0);
  }
}, eventOptions);

// При переходе в другое окно прекращаем управление.
window.addEventListener('blur', () => {
  if (document.pointerLockElement === canvas) document.exitPointerLock();
}, eventOptions);

// Освещение сверху.
new HemisphericLight('light', new Vector3(0, 1, 0), scene);

// Горизонтальная плоскость 10 × 10 метров на высоте Y = 0.
const ground = MeshBuilder.CreateGround(
  'ground',
  { width: 10, height: 10 },
  scene,
);

ground.material = new StandardMaterial('ground-material', scene);

// Используем адрес ведущего из URL страницы, чтобы localhost не указывал
// на собственный ноутбук второго игрока. Путь /ws согласуется с сервером.
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const serverUrl = import.meta.env.VITE_SERVER_WS_URL
  || `${wsProtocol}//${window.location.hostname}:8000/ws`;

const name = (new URLSearchParams(window.location.search).get('name') || 'Игрок').trim().slice(0, 24) || 'Игрок';
const remotePlayers = createRemotePlayers(scene);

const stopStateSender = startStateSender(serverUrl, {
  name,
  getState: () => ({
    x: camera.position.x,
    z: camera.position.z,
    heading: camera.rotation.y,
  }),
  onWelcome: message => {
    // Сервер задаёт начальную позицию заново при каждом подключении.
    camera.position.set(message.x, EYE_HEIGHT, message.z);
    camera.rotation.set(0, message.heading, 0);
    camera.cameraDirection.setAll(0);
    camera.cameraRotation.setAll(0);
  },
  onMessage: message => remotePlayers.handleMessage(message),
  onDisconnect: () => remotePlayers.clear(),
});

// На каждом кадре рисуем сцену из положения камеры.
engine.runRenderLoop(() => {
  remotePlayers.update();
  scene.render();
});

// Подстраиваем размер изображения при изменении окна.
window.addEventListener('resize', () => {
  engine.resize();
}, eventOptions);

function dispose(): void {
  stopStateSender();
  events.abort();
  if (document.pointerLockElement === canvas) document.exitPointerLock();
  engine.stopRenderLoop();
  remotePlayers.dispose();
  scene.dispose();
  engine.dispose();
  canvas.remove();
}

// Перезагрузка модуля не должна оставлять второе соединение и обработчики.
import.meta.hot?.dispose(dispose);
window.addEventListener('pagehide', (event) => {
  if (!event.persisted) dispose();
}, eventOptions);
