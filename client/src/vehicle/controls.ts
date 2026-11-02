import type { VehicleControls } from '../network/protocol';

export function createVehicleControls(canvas: HTMLCanvasElement) {
  const keys = new Set<string>();
  const touchKeys = new Set<string>();
  let respawn = false;
  const movementKeys = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'Space']);
  const events = new AbortController();
  const options = { signal: events.signal };
  const clear = () => {
    keys.clear();
    touchKeys.clear();
    respawn = false;
    canvas.parentElement?.querySelectorAll('.touch-controls .is-pressed')
      .forEach(button => button.classList.remove('is-pressed'));
  };

  const hasGameFocus = () => document.activeElement === canvas
    || Boolean(document.activeElement?.closest('.scenario-assistant'));

  window.addEventListener('keydown', event => {
    if (!hasGameFocus() || event.ctrlKey || event.metaKey) return;
    if (event.code === 'Escape') { clear(); (document.activeElement as HTMLElement | null)?.blur(); return; }
    if (event.code === 'KeyR' && !event.repeat) {
      event.preventDefault();
      respawn = true;
      return;
    }
    if (!movementKeys.has(event.code)) return;
    event.preventDefault();
    keys.add(event.code);
  }, options);
  window.addEventListener('keyup', event => { keys.delete(event.code); }, options);
  window.addEventListener('blur', clear, options);
  document.addEventListener('pointerlockchange', () => { if (document.pointerLockElement !== canvas) { clear(); canvas.blur(); } }, options);
  document.addEventListener('visibilitychange', () => { if (document.hidden) clear(); }, options);

  const touchControls = document.createElement('div');
  touchControls.className = 'touch-controls';
  touchControls.innerHTML = `
    <div class="touch-arrows" aria-label="Управление поворотом">
      <button type="button" data-touch-key="ArrowLeft" aria-label="Повернуть налево">←</button>
      <button type="button" data-touch-key="ArrowRight" aria-label="Повернуть направо">→</button>
    </div>
    <div class="touch-pedals" aria-label="Педали">
      <button type="button" data-touch-key="KeyS" class="touch-brake" aria-label="Тормоз и задний ход"><span class="touch-pedal-face"><span>Тормоз</span></span></button>
      <button type="button" data-touch-key="KeyW" class="touch-throttle" aria-label="Газ"><span class="touch-pedal-face"><span>Газ</span></span></button>
    </div>
  `;
  canvas.parentElement?.append(touchControls);
  touchControls.querySelectorAll<HTMLButtonElement>('[data-touch-key]').forEach(button => {
    const key = button.dataset.touchKey!;
    const press = (event: PointerEvent) => {
      event.preventDefault();
      button.setPointerCapture?.(event.pointerId);
      touchKeys.add(key);
      button.classList.add('is-pressed');
    };
    const release = (event: PointerEvent) => {
      event.preventDefault();
      touchKeys.delete(key);
      button.classList.remove('is-pressed');
    };
    button.addEventListener('pointerdown', press, options);
    button.addEventListener('pointerup', release, options);
    button.addEventListener('pointercancel', release, options);
    button.addEventListener('lostpointercapture', release, options);
  });

  function getControls(): VehicleControls {
    if ((!hasGameFocus() && touchKeys.size === 0) || !document.hasFocus() || document.hidden) {
      return { throttle: 0, steering: 0, brake: 1 };
    }
    return {
      throttle: Number(keys.has('KeyW') || touchKeys.has('KeyW'))
        - Number(keys.has('KeyS') || touchKeys.has('KeyS')),
      steering: Number(keys.has('KeyD') || touchKeys.has('ArrowRight')) - Number(keys.has('KeyA') || touchKeys.has('ArrowLeft')),
      brake: Number(keys.has('Space')),
    };
  }

  const takeRespawn = () => { const requested = respawn; respawn = false; return requested; };
  return { getControls, takeRespawn, clear, dispose: () => { events.abort(); clear(); touchControls.remove(); } };
}
