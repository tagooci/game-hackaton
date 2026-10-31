import './style.css';

import { Engine } from '@babylonjs/core/Engines/engine';
import { Scene } from '@babylonjs/core/scene';
import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera';
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight';
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder';
import { Vector3 } from '@babylonjs/core/Maths/math.vector';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial';
import { startStateSender } from './network/stateSender';
import { createRemotePlayers } from './players/remotePlayers';
import { createVehicleView } from './vehicle/vehicleView';
import { createVehicleControls } from './vehicle/controls';

const events = new AbortController();
const eventOptions = { signal: events.signal };

// Создаём область, в которой Babylon.js будет рисовать.
const canvas = document.createElement('canvas');
document.querySelector<HTMLDivElement>('#app')!.append(canvas);

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
let targetPose = vehicle.getPose();

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
  getControls: controls.getControls,
  onWelcome: message => {
    // Сервер задаёт начальную позицию заново при каждом подключении.
    vehicle.setPose({ x: message.x, z: message.z, heading: message.heading });
    ownId = message.id;
    targetPose = vehicle.getPose();
    controls.clear();
  },
  onMessage: message => {
    if (message.type === 'snapshot') {
      const own = message.players.find(player => player.id === ownId);
      if (own) targetPose = own;
    }
    remotePlayers.handleMessage(message);
  },
  onDisconnect: () => {
    remotePlayers.clear();
    controls.clear();
    targetPose = vehicle.getPose();
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
  });
  remotePlayers.update();
  scene.render();
});

// Подстраиваем размер изображения при изменении окна.
window.addEventListener('resize', () => {
  engine.resize();
}, eventOptions);

function dispose(): void {
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

// Перезагрузка модуля не должна оставлять второе соединение и обработчики.
import.meta.hot?.dispose(dispose);
window.addEventListener('pagehide', (event) => {
  if (!event.persisted) dispose();
}, eventOptions);
