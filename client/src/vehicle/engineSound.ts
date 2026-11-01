/** Local V12-inspired synthesis; no downloads and no server audio traffic. */
export function createEngineSound(host: HTMLElement) {
  let context: AudioContext | undefined;
  let gain: GainNode;
  let filter: BiquadFilterNode;
  let exhaust: OscillatorNode;
  let body: OscillatorNode;
  let disposed = false;
  let failed = false;
  let nextUpdate = 0;
  const events = new AbortController();
  const options = { signal: events.signal };

  function unlock(event: Event) {
    if (disposed || failed || !event.isTrusted) return;
    try {
      if (!context) {
        context = new AudioContext();
        gain = context.createGain();
        gain.gain.value = 0;
        gain.connect(context.destination);
        filter = context.createBiquadFilter();
        filter.type = 'lowpass';
        filter.frequency.value = 650;
        filter.Q.value = 0.5;
        filter.connect(gain);
        exhaust = context.createOscillator();
        // A four-stroke V12 fires six times per crank revolution.
        // Soft harmonics produce a steady exhaust hum without a harsh sawtooth.
        exhaust.setPeriodicWave(context.createPeriodicWave(
          new Float32Array(7), new Float32Array([0, 1, 0.38, 0.18, 0.08, 0.035, 0.015])));
        exhaust.frequency.value = 80;
        exhaust.connect(filter);
        body = context.createOscillator();
        body.type = 'sine';
        body.frequency.value = 800 / 30;
        const bodyGain = context.createGain();
        bodyGain.gain.value = 0.22;
        body.connect(bodyGain).connect(filter);
        exhaust.start();
        body.start();
      }
      if (context.state === 'suspended') void context.resume().catch(() => {});
    } catch {
      failed = true;
      if (context) void context.close().catch(() => {});
      context = undefined;
    }
  }

  host.addEventListener('pointerdown', unlock, options);
  host.addEventListener('keydown', unlock, options);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && context) gain.gain.setTargetAtTime(0, context.currentTime, 0.04);
  }, options);

  return {
    update(speed: number, throttle: number, running: boolean) {
      if (!context || context.state !== 'running' || disposed) return;
      const now = context.currentTime;
      if (now < nextUpdate) return;
      nextUpdate = now + 0.05;
      const load = Number.isFinite(throttle) ? Math.min(1, Math.abs(throttle)) : 0;
      const velocity = Number.isFinite(speed) ? Math.min(1, Math.abs(speed) / 22) : 0;
      const rpm = 800 + velocity * 4700 + load * 1100;
      exhaust.frequency.setTargetAtTime(rpm / 10, now, 0.18);
      body.frequency.setTargetAtTime(rpm / 30, now, 0.22);
      filter.frequency.setTargetAtTime(450 + velocity * 650 + load * 950, now, 0.15);
      const volume = document.hidden || !running ? 0 : 0.025 + load * 0.075 + velocity * 0.025;
      gain.gain.setTargetAtTime(volume, now, 0.1);
    },
    dispose() {
      disposed = true;
      events.abort();
      if (context) {
        gain.gain.value = 0;
        exhaust?.stop();
        body?.stop();
        void context.close().catch(() => {});
      }
    },
  };
}
