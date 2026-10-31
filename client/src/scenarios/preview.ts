import '../style.css';
import { Engine } from '@babylonjs/core/Engines/engine';
import { FreeCamera } from '@babylonjs/core/Cameras/freeCamera';
import { Vector3 } from '@babylonjs/core/Maths/math.vector';
import { createJunctionScene, createVehicle } from './junctionScene';
import { loadJunction } from './definition';

// Offline asset preview only. Production control and physics belong to the host.
const abort = new AbortController();
const panel = document.createElement('section');
panel.className = 'scenario-panel';
panel.innerHTML = '<h1>Перекрёсток · просмотр</h1><p>Локальная проверка карты и моделей. Без сети и оценки ПДД.</p><label>Транспорт <select><option value="car">Легковая</option><option value="truck">КамАЗ</option><option value="tram">Трамвай</option></select></label><p>W/S — движение, A/D — руление. Трамвай следует рельсам.</p><p><a href="/">Открыть сетевой клиент v1</a></p><output>Загрузка карты…</output>';
document.body.append(panel);
const canvas = document.createElement('canvas');
document.querySelector('#app')!.append(canvas);
const engine = new Engine(canvas, true);
try {
  const definition = await loadJunction(abort.signal);
  const scene = createJunctionScene(engine, definition);
  const vehicles = definition.roles.map(role => ({ role, mesh: createVehicle(scene, role, role.roleId) }));
  const camera = new FreeCamera('hood-camera', new Vector3(0, 2, 0), scene);
  camera.inputs.clear();
  camera.minZ = .1;
  let selected = vehicles[0];
  let speed = 0;
  const keys = new Set<string>();
  const output = panel.querySelector('output')!;
  const select = panel.querySelector('select')!;
  select.addEventListener('change', () => {
    selected = vehicles.find(v => v.role.vehicleType === select.value)!;
    speed = 0;
    keys.clear();
  }, { signal: abort.signal });
  window.addEventListener('keydown', event => {
    if (event.target instanceof HTMLSelectElement) return;
    if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'Space'].includes(event.code)) {
      event.preventDefault();
      keys.add(event.code);
    }
  }, { signal: abort.signal });
  window.addEventListener('keyup', e => keys.delete(e.code), { signal: abort.signal });
  window.addEventListener('blur', () => { keys.clear(); speed = 0; }, { signal: abort.signal });
  engine.runRenderLoop(() => {
    const dt = Math.min(.05, engine.getDeltaTime() / 1000);
    const throttle = Number(keys.has('KeyW')) - Number(keys.has('KeyS'));
    speed = Math.max(-3, Math.min(7, speed + throttle * 3 * dt));
    if (!throttle || keys.has('Space')) speed *= Math.exp(-4 * dt);
    const steering = Number(keys.has('KeyD')) - Number(keys.has('KeyA'));
    if (selected.role.vehicleType !== 'tram') selected.mesh.rotation.y += steering * speed * dt / 5;
    selected.mesh.position.x += Math.sin(selected.mesh.rotation.y) * speed * dt;
    selected.mesh.position.z += Math.cos(selected.mesh.rotation.y) * speed * dt;
    const heading = selected.mesh.rotation.y;
    const eyeHeight = selected.role.vehicleType === 'car' ? 1.35 : 2.65;
    const offset = selected.role.length / 2 - .65;
    camera.position.set(selected.mesh.position.x + Math.sin(heading) * offset, eyeHeight,
                        selected.mesh.position.z + Math.cos(heading) * offset);
    camera.rotation.set(.04, heading, 0);
    output.textContent = `${definition.title} · ${Math.abs(speed * 3.6).toFixed(0)} км/ч`;
    scene.render();
  });
  window.addEventListener('resize', () => engine.resize(), { signal: abort.signal });
  function dispose() {
    abort.abort();
    engine.stopRenderLoop();
    scene.dispose();
    engine.dispose();
    panel.remove();
    canvas.remove();
  }
  import.meta.hot?.dispose(dispose);
  window.addEventListener('pagehide', dispose, { once: true, signal: abort.signal });
} catch (error) {
  panel.querySelector('output')!.textContent = `Ошибка загрузки: ${String(error)}`;
  engine.dispose();
}
