import type { VehicleControls } from '../network/protocol';

export function createVehicleControls(canvas: HTMLCanvasElement) {
  const keys = new Set<string>();
  const movementKeys = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'Space']);
  const events = new AbortController();
  const options = { signal: events.signal };
  const clear = () => keys.clear();

  window.addEventListener('keydown', event => {
    if (document.activeElement !== canvas || event.ctrlKey || event.metaKey || !movementKeys.has(event.code)) return;
    event.preventDefault();
    keys.add(event.code);
  }, options);
  window.addEventListener('keyup', event => { keys.delete(event.code); }, options);
  window.addEventListener('blur', clear, options);
  document.addEventListener('visibilitychange', () => { if (document.hidden) clear(); }, options);

  function getControls(): VehicleControls {
    if (document.activeElement !== canvas || !document.hasFocus() || document.hidden) {
      return { throttle: 0, steering: 0, brake: 1 };
    }
    return {
      throttle: Number(keys.has('KeyW')) - Number(keys.has('KeyS')),
      steering: Number(keys.has('KeyD')) - Number(keys.has('KeyA')),
      brake: Number(keys.has('Space')),
    };
  }

  return { getControls, clear, dispose: () => { events.abort(); clear(); } };
}
