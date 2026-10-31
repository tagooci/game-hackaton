import "./style.css";

import {
  Engine,
  Scene,
  FreeCamera,
  Vector3,
  HemisphericLight,
  MeshBuilder,
  StandardMaterial,
  Color3,
  Color4,
} from "@babylonjs/core";

const canvas = document.querySelector("#renderCanvas");
const engine = new Engine(canvas, true);
const scene = new Scene(engine);

scene.clearColor = new Color4(0.76, 0.85, 0.92, 1);

// Оставляем левостороннюю систему Babylon.js:
// Y — вверх, при нулевом повороте смотрим вдоль +Z.
scene.useRightHandedSystem = false;

const light = new HemisphericLight(
  "mainLight",
  new Vector3(0, 1, 0),
  scene,
);

light.intensity = 0.9;

function createMaterial(name, color) {
  const material = new StandardMaterial(name, scene);
  material.diffuseColor = Color3.FromHexString(color);
  material.specularColor = Color3.Black();
  return material;
}

// Площадка пока служит визуальным окружением.
// Серверные границы движения добавим при подключении сети.
const ground = MeshBuilder.CreateGround(
  "ground",
  { width: 30, height: 30, subdivisions: 1 },
  scene,
);

ground.material = createMaterial("groundMaterial", "#87AE83");

// Тело собственного игрока.
// Координаты X/Z и rotation.y позже отправим на сервер.
const player = MeshBuilder.CreateCapsule(
  "localPlayer",
  {
    height: 1.8,
    radius: 0.35,
    tessellation: 12,
    subdivisions: 1,
  },
  scene,
);

player.position.set(0, 0.9, 0);

// Изнутри капсулы её поверхность мешала бы обзору.
// Скрываем геометрию, сам объект продолжает хранить позицию и поворот.
player.isVisible = false;

// Камера — дочерний объект игрока:
// она перемещается и поворачивается вместе с его телом.
//
// Координаты камеры здесь локальные, относительно центра капсулы.
// 0.9 + 0.7 = 1.6 метра над землёй — высота глаз.
const camera = new FreeCamera(
  "firstPersonCamera",
  new Vector3(0, 0.7, 0),
  scene,
);

camera.parent = player;
camera.minZ = 0.05;
scene.activeCamera = camera;

// Управление реализуем сами, чтобы движение и heading
// полностью соответствовали вашему протоколу.
camera.inputs.clear();

// Несколько ориентиров: на однотонной земле движение плохо заметно.
// Коллизий у них пока нет.
const markerMaterial = createMaterial("markerMaterial", "#EB915B");

for (const [x, z] of [
  [-5, 5],
  [5, 5],
  [-5, -5],
  [5, -5],
]) {
  const marker = MeshBuilder.CreateBox(
    `marker_${x}_${z}`,
    { size: 1 },
    scene,
  );

  marker.position.set(x, 0.5, z);
  marker.material = markerMaterial;
}

// Скорость в метрах в секунду, чувствительность — радианы
// поворота на единицу относительного движения мыши.
const MOVE_SPEED = 4;
const MOUSE_SENSITIVITY = 0.002;

// Не даём взгляду перевернуться при движении мыши вверх/вниз.
const PITCH_LIMIT = Math.PI / 2 - 0.05;

const pressedKeys = new Set();
const movementKeys = new Set(["KeyW", "KeyA", "KeyS", "KeyD"]);

function isMouseLocked() {
  return document.pointerLockElement === canvas;
}

// Захват курсора разрешён браузером после действия пользователя.
// Повторный клик после Esc снова включает управление.
canvas.addEventListener("click", () => {
  if (!isMouseLocked()) {
    canvas.requestPointerLock();
  }
});

document.addEventListener("pointerlockerror", () => {
  console.warn("Не удалось захватить курсор. Нажми на сцену ещё раз.");
});

document.addEventListener("mousemove", (event) => {
  if (!isMouseLocked()) return;

  // Горизонтальный поворот принадлежит телу.
  // Это и есть будущий heading, без пересчёта осей.
  player.rotation.y += event.movementX * MOUSE_SENSITIVITY;

  // Держим угол около диапазона [-π, π], чтобы он не рос бесконечно.
  player.rotation.y = Math.atan2(
    Math.sin(player.rotation.y),
    Math.cos(player.rotation.y),
  );

  // Вертикальный наклон принадлежит только камере.
  camera.rotation.x += event.movementY * MOUSE_SENSITIVITY;

  camera.rotation.x = Math.max(
    -PITCH_LIMIT,
    Math.min(PITCH_LIMIT, camera.rotation.x),
  );
});

window.addEventListener("keydown", (event) => {
  if (!isMouseLocked() || !movementKeys.has(event.code)) return;

  event.preventDefault();

  // event.code соответствует физической клавише:
  // WASD работает и при русской раскладке.
  pressedKeys.add(event.code);
});

window.addEventListener("keyup", (event) => {
  pressedKeys.delete(event.code);
});

// Сбрасываем кнопки при потере фокуса или освобождении курсора,
// иначе персонаж может продолжить идти после переключения окна.
window.addEventListener("blur", () => {
  pressedKeys.clear();
});

document.addEventListener("pointerlockchange", () => {
  pressedKeys.clear();
});

engine.runRenderLoop(() => {
  // Переводим миллисекунды в секунды.
  // Ограничиваем шаг после зависания или возвращения на вкладку.
  const deltaTime = Math.min(engine.getDeltaTime() / 1000, 0.05);

  if (isMouseLocked()) {
    // Направления относительно тела: вперёд/назад и вправо/влево.
    let forward =
      Number(pressedKeys.has("KeyW")) -
      Number(pressedKeys.has("KeyS"));

    let right =
      Number(pressedKeys.has("KeyD")) -
      Number(pressedKeys.has("KeyA"));

    // Нормализация: по диагонали идём с той же скоростью.
    const length = Math.hypot(forward, right);

    if (length > 0) {
      forward /= length;
      right /= length;

      const heading = player.rotation.y;
      const distance = MOVE_SPEED * deltaTime;

      // Переводим движение относительно тела в мировые X/Z.
      // При heading = 0: вперёд — +Z, вправо — +X.
      player.position.x +=
        (Math.sin(heading) * forward +
          Math.cos(heading) * right) * distance;

      player.position.z +=
        (Math.cos(heading) * forward -
          Math.sin(heading) * right) * distance;
    }
  }

  scene.render();
});

window.addEventListener("resize", () => {
  engine.resize();
});