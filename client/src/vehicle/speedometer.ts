/** SVG-шкала 0–100 км/ч, стрелка вращается вокруг точки 240,240. */
export function createSpeedometer(host: HTMLElement) {
  const root = document.createElement('div');
  root.className = 'speedometer';
  const scale = document.createElement('img');
  scale.src = '/assets/speedometer/scale.svg'; scale.alt = '';
  const needle = document.createElement('img');
  needle.src = '/assets/speedometer/needle.svg'; needle.alt = ''; needle.className = 'speedometer-needle';
  const value = document.createElement('div'); value.className = 'speedometer-value';
  root.append(scale, needle, value); host.append(root);
  let displayed = -1;
  return {
    update(speedMps: number) {
      const speed = Math.abs(speedMps) * 3.6;
      needle.style.transform = `rotate(${-90 + Math.min(speed, 100) * 1.8}deg)`;
      const rounded = Math.round(speed);
      if (rounded !== displayed) { value.textContent = `${rounded} км/ч`; displayed = rounded; }
    },
    dispose() { root.remove(); },
  };
}
