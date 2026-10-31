/** Host integration adapter: the v2 transport owns validation, ticks and input.
 * Inject the content manager here so published content goes through its budget.
 */
export interface PreparedScene { dispose(): void }
export interface ScenePrepare {
  sceneId: string; epoch: number; plan: { revision: number };
}
export interface TransitionHost {
  setControlsEnabled(enabled: boolean): void;
  clearVehicles(): void;
  load(message: ScenePrepare, signal: AbortSignal): Promise<PreparedScene>;
  send(message: Record<string, unknown>): void;
}

export function createScenarioTransition(host: TransitionHost) {
  let current: ScenePrepare | undefined;
  let pending: AbortController | undefined;
  let scene: PreparedScene | undefined;
  let ready = false;
  let startTick: number | undefined;
  let disposed = false;

  async function prepare(message: ScenePrepare) {
    if (disposed || (current && message.epoch <= current.epoch)) return;
    current = message;
    pending?.abort();
    const request = new AbortController();
    pending = request;
    host.setControlsEnabled(false);
    host.clearVehicles();
    scene?.dispose();
    scene = undefined;
    ready = false;
    startTick = undefined;
    try {
      const loaded = await host.load(message, request.signal);
      if (request.signal.aborted || disposed || current !== message) {
        loaded.dispose();
        return;
      }
      scene = loaded;
      ready = true;
      host.send({ type: 'scene_ready', sceneId: message.sceneId, epoch: message.epoch,
                  revision: message.plan.revision });
    } catch {
      if (!request.signal.aborted && !disposed && current === message) {
        host.send({ type: 'scene_failed', sceneId: message.sceneId, epoch: message.epoch,
                    reason: 'scene_build_failed' });
      }
    }
  }

  function start(message: { sceneId: string; epoch: number; startTick: number }) {
    if (ready && current?.sceneId === message.sceneId && current.epoch === message.epoch) {
      startTick = message.startTick;
    }
  }

  function tick(sceneId: string, epoch: number, tick: number) {
    if (ready && current?.sceneId === sceneId && current.epoch === epoch &&
        startTick !== undefined && tick >= startTick) host.setControlsEnabled(true);
  }

  function finish() {
    ready = false;
    startTick = undefined;
    host.setControlsEnabled(false);
  }

  function dispose() {
    disposed = true;
    pending?.abort();
    finish();
    scene?.dispose();
    scene = undefined;
    current = undefined;
  }
  return { prepare, start, tick, finish, dispose };
}
