import { createSpeedometer } from './vehicle/speedometer';
import './style.css';
import { createMusicPlayer } from './hud/musicPlayer.js';
import { createScenarioAssistant, showAssistantPreview } from './assistant/scenarioAssistant';
import { api, ApiError, showAuth, showGarage } from './auth/session';
import type { Account, Profile } from './auth/session';

import { createFinishArch } from './world/finishArch';
import { RoadContent } from './world/road-content.js';
import { Engine } from '@babylonjs/core/Engines/engine';
import { Scene } from '@babylonjs/core/scene';
import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera';
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight';
import { DirectionalLight } from '@babylonjs/core/Lights/directionalLight';
import { ShadowGenerator } from '@babylonjs/core/Lights/Shadows/shadowGenerator';
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder';
import { Matrix, Vector3 } from '@babylonjs/core/Maths/math.vector';
import { Color3, Color4 } from '@babylonjs/core/Maths/math.color';
import type { VehiclePose } from './vehicle/vehicleView';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial';
import { startStateSender } from './network/stateSender';
import { createRemotePlayers } from './players/remotePlayers';
import { createVehicleView, VEHICLE_LENGTH } from './vehicle/vehicleView';
import { createVehicleControls } from './vehicle/controls';

const host = document.querySelector<HTMLDivElement>('#app')!;
let stopScreen = () => {};
let disposed = false;

function authScreen(error = ''): void {
  stopScreen();
  stopScreen = showAuth(host, enterGame, error);
}

async function enterGame(account: Account): Promise<void> {
  const profile = await api<Profile>('profile');
  stopScreen();
  stopScreen = showGarage(host, profile, selected => startAfterGarage(account, selected));
}

async function startAfterGarage(account: Account, profile: Profile): Promise<void> {
  await api('content/bootstrap');
  if (disposed) return;
  stopScreen();
  host.replaceChildren();
  stopScreen = startGame(account, profile);
}

function startGame(account: Account, profile: Profile): () => void {
  const events = new AbortController();
  const eventOptions = { signal: events.signal };

  // Создаём область, в которой Babylon.js будет рисовать.
  const canvas = document.createElement('canvas');
  host.append(canvas);

  // Движок управляет отрисовкой.
  const engine = new Engine(canvas, true);

  // Сцена содержит камеру, свет и объекты.
  const scene = new Scene(engine);
  scene.clearColor = new Color4(0.86, 0.83, 0.76, 1);
  // Дальняя граница подгрузки скрыта за плавным туманом.
  scene.fogMode = Scene.FOGMODE_LINEAR;
  scene.fogColor = new Color3(0.86, 0.83, 0.76);
  scene.fogStart = 40;
  scene.fogEnd = 60;

  // Длина модели в метрах; пропорции сохраняются при загрузке.
  const vehicle = createVehicleView(scene, VEHICLE_LENGTH);
  vehicle.setPose({ x: 0, z: 0, heading: 0, color: profile.vehicleColor });

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
  camera.maxZ = 140;
  camera.lowerRadiusLimit = 5;
  camera.upperRadiusLimit = 12;
  camera.lowerBetaLimit = 0.2;
  camera.upperBetaLimit = Math.PI / 2 - 0.05;
  camera.panningSensibility = 0;
  camera.inputs.removeByType('ArcRotateCameraKeyboardMoveInput');
  camera.attachControl(canvas, false);
  scene.activeCamera = camera;
  canvas.tabIndex = 0;
  const controls = createVehicleControls(canvas);
  const speedometer = createSpeedometer(host);
  const assistant = createScenarioAssistant(host, () => {
    controls.clear();
    if (document.pointerLockElement === canvas) document.exitPointerLock();
  });
  let agentReplies: string[] = [];
  let agentExperience = '';
  let feedbackSession = '';
  let lastScenarioResult = '';
  let inScenario = false;
  let ownId = '';
  let targetPose: VehiclePose = vehicle.getPose();

  // Освещение сверху.
  const ambient = new HemisphericLight('sky', Vector3.Up(), scene);
  ambient.intensity = 0.6;
  ambient.diffuse = new Color3(1, 0.96, 0.88);
  ambient.groundColor = new Color3(0.42, 0.39, 0.33);
  const sun = new DirectionalLight('sun', new Vector3(-0.4, -1, -0.3).normalize(), scene);
  sun.diffuse = new Color3(1, 0.88, 0.7);
  sun.intensity = 1.0;
  sun.shadowFrustumSize = 130;
  sun.shadowMinZ = 1;
  sun.shadowMaxZ = 160;
  const shadows = new ShadowGenerator(2048, sun);
  shadows.usePercentageCloserFiltering = true;
  shadows.bias = 0.001;
  shadows.normalBias = 0.08;
  shadows.setDarkness(0.25);

  // Земля под картой; локальная сетка с шагом 1 м следует за машиной.
  const ground = MeshBuilder.CreateGround(
    'ground',
    { width: 2700, height: 2300 },
    scene,
  );

  const groundMaterial = new StandardMaterial('ground-material', scene);
  groundMaterial.diffuseColor = Color3.FromHexString('#77776c').toLinearSpace();
  groundMaterial.specularColor = Color3.Black();
  ground.position.y = -0.12;
  ground.material = groundMaterial;
  ground.receiveShadows = true;
  const overlay = document.createElement('div');
  overlay.className = 'loading-screen';
  overlay.textContent = 'Подключение…';
  canvas.addEventListener('click', async () => {
    if (!overlay.hidden || document.pointerLockElement === canvas) return;
    canvas.focus({ preventScroll: true });
    try { if (!assistant.isOpen) await canvas.requestPointerLock?.(); }
    catch { /* Keyboard controls also work in browsers without pointer lock. */ }
  }, eventOptions);
  const logout = document.createElement('button');
  logout.className = 'logout logout--with-player';
  logout.textContent = `Выйти (${account.name})`;
  host.append(overlay, logout);
  const musicPlayer = createMusicPlayer(host);
  logout.onclick = async () => {
    logout.disabled = true;
    try { await api('logout', {}); authScreen(); }
    catch { overlay.hidden = false; overlay.textContent = 'Не удалось выйти. Попробуйте ещё раз.'; logout.disabled = false; }
  };
  const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const serverUrl = `${wsProtocol}//${location.host}/ws/v2`;
  const queueLabel = document.createElement('div');
  queueLabel.className = 'scenario-queue';
  queueLabel.hidden = true;
  host.append(queueLabel);
  let finishArch: ReturnType<typeof createFinishArch> | undefined;
  let queuePosition: Vector3 | undefined;
  const remotePlayers = createRemotePlayers(scene);
  const roads = new RoadContent(scene, () => {});
  if (import.meta.env.DEV) Object.defineProperty(window, 'roadCache', { configurable: true, get: () => roads.stats() });
  let mapReady = false;
  let mapLoading = false;
  let mapError = false;
  const neutralControls = { throttle: 0, steering: 0, brake: 1 };

  function updateRoads(x: number, z: number): Promise<void> {
    mapLoading = true;
    return roads.update(x, z).then(() => {
      mapLoading = false;
      mapError = false;
    }).catch(error => {
      mapLoading = false;
      mapError = true;
      overlay.hidden = false;
      overlay.textContent = `Ошибка карты: ${error.message}. Перезагрузите страницу.`;
      throw error;
    });
  }
  const stopStateSender = startStateSender(serverUrl, {
    getControls: () => mapError || assistant.isOpen ? neutralControls : controls.getControls(),
    takeRespawn: controls.takeRespawn,
    prepareScene: async message => {
      const expected = new Set(['car-kit/sedan.glb.bin']);
      if (message.plan.resources.length !== expected.size || message.plan.resources.some(r => !expected.has(r.id))) {
        throw new Error('Неподдерживаемый план сцены');
      }
      mapReady = false;
      overlay.textContent = 'Загрузка карты…';
      await roads.init(message.plan.mapManifestUrl);
      if (roads.manifest.groundColor) groundMaterial.diffuseColor = Color3.FromHexString(roads.manifest.groundColor).toLinearSpace();
      await roads.update(message.spawn.x, message.spawn.z);
      overlay.textContent = 'Загрузка машины…';
      await vehicle.ready;
      overlay.textContent = 'Подготовка сцены…';
      await scene.whenReadyAsync();
      mapReady = true;
    },
    onStatus: text => { if (!mapLoading && !mapError) { overlay.hidden = !text; overlay.textContent = text; } },
    onSessionEnd: code => authScreen(code === 4001 ? 'Аккаунт уже подключён в другом окне' : 'Войдите в аккаунт снова'),
    onMessage: message => {
      if (message.type === 'scenario_reward' && message.sessionId === feedbackSession) {
        agentExperience = `${message.experience} XP`;
        if (!inScenario) {
          if (agentReplies.length) assistant.result(agentReplies, agentExperience);
          else assistant.waiting(agentExperience);
        }
      }
      if (message.type === 'agent_feedback' || message.type === 'agent_feedback_error') {
        window.dispatchEvent(new CustomEvent('agent-feedback', { detail: message }));
        console.info('Agent feedback:', message);
        if (message.sessionId === feedbackSession) {
          if (message.type === 'agent_feedback') agentExperience = message.feedback.experience;
          agentReplies = message.type === 'agent_feedback_error' ? [message.text] : [
            ...message.feedback.successful.map(item => item.comment),
            ...message.feedback.errors.map(item => item.comment),
          ];
          if (!inScenario && agentReplies.length) assistant.result(agentReplies, agentExperience);
        }
      }
      if (message.type === 'welcome') ownId = message.playerId;
      if (message.type === 'scene_prepare') {
        const returnedFromScenario = inScenario && message.sceneKind === 'world';
        inScenario = message.sceneKind === 'scenario';
        if (inScenario) {
          lastScenarioResult = '';
          agentReplies = [];
          agentExperience = '';
          feedbackSession = message.sceneId;
          assistant.hide();
        } else if (returnedFromScenario && agentReplies.length) {
          assistant.result(agentReplies, agentExperience);
        } else if (returnedFromScenario) {
          assistant.waiting(agentExperience);
        } else if (!lastScenarioResult) assistant.hide();
        queuePosition = undefined; queueLabel.hidden = true;
        finishArch?.dispose();
        finishArch = message.finish ? createFinishArch(scene, message.finish) : undefined;
        controls.clear();
        vehicle.setPose(message.spawn);
        targetPose = message.spawn;
        scene.fogStart = message.weather === 'fog' ? 18 : 40;
        scene.fogEnd = message.weather === 'fog' ? 42 : 60;
        scene.fogColor = message.weather === 'rain'
          ? new Color3(0.35, 0.4, 0.48)
          : new Color3(0.86, 0.83, 0.76);
        scene.clearColor = message.weather === 'rain'
          ? new Color4(0.35, 0.4, 0.48, 1)
          : new Color4(0.86, 0.83, 0.76, 1);
        sun.intensity = message.weather === 'rain' ? 0.55 : 1.0;
      }

      if (message.type === 'snapshot') {
        if (inScenario && typeof message.scenarioResult === 'string' && message.scenarioResult && message.scenarioResult !== lastScenarioResult) {
          lastScenarioResult = message.scenarioResult;
        }
        const queue = message.scenarioQueue;
        queuePosition = queue ? new Vector3(queue.x, queue.y, queue.z) : undefined;
        queueLabel.textContent = queue ? `${queue.count}/2` : '';
        const own = message.players.find(player => player.id === ownId);
        if (own) targetPose = own;
      }
      remotePlayers.handleMessage(message);
    },
    onDisconnect: () => {
      mapReady = false;
      assistant.hide(); lastScenarioResult = ''; agentReplies = []; agentExperience = ''; feedbackSession = ''; inScenario = false;
      remotePlayers.clear(); controls.clear(); targetPose = { ...vehicle.getPose(), speed: 0, throttle: 0 };
    },
  });

  // На каждом кадре рисуем сцену из положения камеры.
  engine.runRenderLoop(() => {
    // Сглаживание отрисовки, не расчёт физики: движемся только к позиции сервера.
    const pose = vehicle.getPose();
    const blend = 1 - Math.exp(-20 * Math.min(engine.getDeltaTime() / 1000, 0.1));
    const suspensionBlend = 1 - Math.exp(-8 * Math.min(engine.getDeltaTime() / 1000, 0.1));
    const angle = Math.atan2(Math.sin(targetPose.heading - pose.heading), Math.cos(targetPose.heading - pose.heading));
    vehicle.setPose({
      x: pose.x + (targetPose.x - pose.x) * blend,
      z: pose.z + (targetPose.z - pose.z) * blend,
      heading: pose.heading + angle * blend,
      y: (pose.y ?? 0) + ((targetPose.y ?? 0) - (pose.y ?? 0)) * suspensionBlend,
      pitch: (pose.pitch ?? 0) + ((targetPose.pitch ?? 0) - (pose.pitch ?? 0)) * suspensionBlend,
      wheelAngle: (pose.wheelAngle ?? 0) + ((targetPose.wheelAngle ?? 0) - (pose.wheelAngle ?? 0)) * blend,
      color: targetPose.color,
      throttle: targetPose.throttle, grounded: targetPose.grounded,
    });
    speedometer.update(targetPose.speed ?? 0);
    if (mapReady && !mapLoading && !mapError) {
      const size = roads.manifest.streamStep ?? roads.manifest.chunkSize;
      const key = `${Math.floor(pose.x / size)}:${Math.floor(pose.z / size)}:none`;
      if (key !== roads.planKey) {
        void updateRoads(pose.x, pose.z).catch(() => {});
      }
    }
    if (queuePosition && mapReady) {
      const projected = Vector3.Project(queuePosition, Matrix.Identity(), scene.getTransformMatrix(),
        camera.viewport.toGlobal(engine.getRenderWidth(), engine.getRenderHeight()));
      queueLabel.hidden = projected.z < 0 || projected.z > 1 || Vector3.Distance(camera.position, queuePosition) > 60;
      queueLabel.style.left = `${projected.x / engine.getRenderWidth() * canvas.clientWidth}px`;
      queueLabel.style.top = `${projected.y / engine.getRenderHeight() * canvas.clientHeight}px`;
    } else queueLabel.hidden = true;
    remotePlayers.update();
    // Одна карта теней вокруг игрока; выгруженные meshes автоматически исчезают из списка.
    sun.position.set(pose.x + 32, 80, pose.z + 24);
    shadows.getShadowMap()!.renderList = scene.meshes.filter(mesh =>
      mesh !== ground && mesh.isEnabled() && mesh.isVisible && mesh.getTotalVertices() > 0);
    scene.render();
  });

  // Подстраиваем размер изображения при изменении окна.
  window.addEventListener('resize', () => {
    engine.resize();
  }, eventOptions);

  function dispose(): void {
    if (document.pointerLockElement === canvas) document.exitPointerLock();
    stopStateSender();
    assistant.dispose();
    musicPlayer.dispose();
    controls.dispose();
    speedometer.dispose();
    events.abort();
    engine.stopRenderLoop();
    if (import.meta.env.DEV) Reflect.deleteProperty(window, 'roadCache');
    roads.dispose();
    remotePlayers.dispose();
    vehicle.dispose();
    scene.dispose();
    engine.dispose();
    canvas.remove();
  }

  return () => { dispose(); overlay.remove(); logout.remove(); queueLabel.remove(); finishArch?.dispose(); };
}

if (new URLSearchParams(location.search).has('assistant-preview')) {
  stopScreen = showAssistantPreview(host);
} else {
host.textContent = 'Проверка сессии…';
api<Account>('me').then(enterGame).catch(error => {
  if (!disposed) authScreen(error instanceof ApiError && error.status === 401 ? '' : 'Не удалось подключиться к серверу');
});
}
function disposeApplication(): void { disposed = true; stopScreen(); }
import.meta.hot?.dispose(disposeApplication);
window.addEventListener('pagehide', event => { if (!event.persisted) disposeApplication(); });
