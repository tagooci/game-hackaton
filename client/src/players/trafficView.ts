import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader.js';
import { TransformNode } from '@babylonjs/core/Meshes/transformNode.js';
import type { AssetContainer, InstantiatedEntries } from '@babylonjs/core/assetContainer.js';
import type { Scene } from '@babylonjs/core/scene.js';
import '@babylonjs/loaders/glTF/2.0/glTFLoader.js';
import type { TrafficSnapshot } from '../network/protocol';

const MODEL_IDS = new Set([
  'sedan', 'sedan-sports', 'suv', 'taxi', 'van', 'truck', 'ambulance', 'police', 'firetruck',
]);
const INTERPOLATION_DELAY_MS = 90;
const MODEL_LENGTHS: Record<string, number> = {
  sedan: 3.3, 'sedan-sports': 3.3, suv: 3.5, taxi: 3.3, van: 3.6,
  truck: 4.0, ambulance: 3.6, police: 3.3, firetruck: 4.0,
};

interface TrafficSample extends TrafficSnapshot { time: number }
interface TrafficView {
  model: string;
  root: TransformNode;
  instance: InstantiatedEntries;
  samples: TrafficSample[];
}

type ModelLoader = (model: string, signal: AbortSignal) => Promise<AssetContainer>;

async function loadTrafficModel(scene: Scene, model: string, signal: AbortSignal): Promise<AssetContainer> {
  const response = await fetch(`/assets/traffic/${model}.glb`, { cache: 'no-store', signal });
  if (!response.ok) throw new Error(`NPC model ${model}: HTTP ${response.status}`);
  const data = new Uint8Array(await response.arrayBuffer());
  signal.throwIfAborted();
  return LoadAssetContainerAsync(data, scene, { pluginExtension: '.glb', rootUrl: '/assets/traffic/' });
}

/** Client rendering for server-authoritative NPCs. Never runs in isolated scenarios. */
export function createTrafficView(scene: Scene, isChunkLoaded: (state: TrafficSnapshot) => boolean,
  loadModel: ModelLoader = (model, signal) => loadTrafficModel(scene, model, signal)) {
  const latest = new Map<string, TrafficSample>();
  const views = new Map<string, TrafficView>();
  const creating = new Set<string>();
  const loading = new Map<string, { promise: Promise<AssetContainer>; controller: AbortController }>();
  const containers = new Map<string, AssetContainer>();
  const neededModels = new Set<string>();
  let enabled = true;
  let disposed = false;

  async function getContainer(model: string): Promise<AssetContainer> {
    const cached = containers.get(model);
    if (cached) return cached;
    const existing = loading.get(model);
    if (existing) return existing.promise;
    const controller = new AbortController();
    const promise = (async () => {
      const container = await loadModel(model, controller.signal);
      if (disposed || !enabled || scene.isDisposed || controller.signal.aborted || !neededModels.has(model)) {
        container.dispose();
        throw new DOMException('NPC chunk unloaded', 'AbortError');
      }
      containers.set(model, container);
      return container;
    })().finally(() => {
      if (loading.get(model)?.controller === controller) loading.delete(model);
    });
    loading.set(model, { promise, controller });
    return promise;
  }

  function disposeView(id: string): void {
    const view = views.get(id);
    if (!view) return;
    views.delete(id);
    view.root.dispose();
    view.instance.dispose();
  }

  async function addView(state: TrafficSample): Promise<void> {
    if (!MODEL_IDS.has(state.model) || creating.has(state.id)) return;
    const id = state.id;
    const model = state.model;
    creating.add(id);
    try {
      const container = await getContainer(model);
      const current = latest.get(id);
      if (disposed || !enabled || views.has(id) || current?.model !== model || !isChunkLoaded(current)) return;
      const root = new TransformNode(`traffic-${id}`, scene);
      const modelRoot = new TransformNode(`traffic-${id}-model`, scene);
      modelRoot.parent = root;
      const instance = container.instantiateModelsToScene(name => `traffic-${id}-${name}`, false, { doNotInstantiate: true });
      for (const node of instance.rootNodes) node.parent = modelRoot;
      const bounds = modelRoot.getHierarchyBoundingVectors(true);
      const size = bounds.max.subtract(bounds.min);
      const height = model === 'truck' || model === 'firetruck' ? 2.2 : 1.7;
      const sx = 1.9 / Math.max(size.x, 0.01);
      const sy = height / Math.max(size.y, 0.01);
      const sz = MODEL_LENGTHS[model] / Math.max(size.z, 0.01);
      modelRoot.scaling.set(sx, sy, sz);
      modelRoot.position.set(-(bounds.min.x + bounds.max.x) * sx / 2, -bounds.min.y * sy, -(bounds.min.z + bounds.max.z) * sz / 2);
      root.setEnabled(true);
      const sample = latest.get(id);
      if (!sample || sample.model !== model) { root.dispose(); instance.dispose(); return; }
      views.set(id, { model, root, instance, samples: [{ ...sample }] });
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) console.error(`Не удалось создать NPC ${id}:`, error);
    } finally {
      creating.delete(id);
    }
  }

  function handleSnapshot(states: TrafficSnapshot[], now = performance.now()): void {
    if (!enabled) return;
    const loaded = states.filter(state => MODEL_IDS.has(state.model) && isChunkLoaded(state));
    const present = new Set(loaded.map(state => state.id));
    for (const id of latest.keys()) if (!present.has(id)) latest.delete(id);
    for (const id of [...views.keys()]) if (!present.has(id)) disposeView(id);
    for (const state of loaded) {
      const sample = { ...state, time: now };
      latest.set(state.id, sample);
      const view = views.get(state.id);
      if (view && view.model !== state.model) disposeView(state.id);
      const current = views.get(state.id);
      if (current) {
        current.samples.push(sample);
        if (current.samples.length > 8) current.samples.shift();
      }
    }
  }

  function setEnabled(value: boolean): void {
    enabled = value;
    if (!value) {
      latest.clear();
      for (const id of [...views.keys()]) disposeView(id);
      for (const container of containers.values()) container.dispose();
      containers.clear();
      neededModels.clear();
      for (const request of loading.values()) request.controller.abort();
      loading.clear();
    }
  }

  function update(now = performance.now()): void {
    if (!enabled || disposed) return;
    for (const [id, state] of latest) if (!isChunkLoaded(state)) latest.delete(id);
    const active = new Map([...latest].filter(([, state]) => MODEL_IDS.has(state.model) && isChunkLoaded(state)));
    for (const id of [...views.keys()]) if (!active.has(id)) disposeView(id);
    neededModels.clear();
    for (const state of active.values()) neededModels.add(state.model);
    for (const [model, container] of containers) if (!neededModels.has(model)) {
      container.dispose();
      containers.delete(model);
    }
    for (const [model, request] of loading) if (!neededModels.has(model)) {
      request.controller.abort();
      loading.delete(model);
    }
    for (const [id, state] of active) if (!views.has(id)) void addView(state);
    const renderTime = now - INTERPOLATION_DELAY_MS;
    for (const view of views.values()) {
      const samples = view.samples;
      while (samples.length > 2 && samples[1].time <= renderTime) samples.shift();
      const from = samples[0];
      const to = samples[1] ?? from;
      const t = to.time > from.time ? Math.max(0, Math.min(1, (renderTime - from.time) / (to.time - from.time))) : 1;
      const angle = Math.atan2(Math.sin(to.heading - from.heading), Math.cos(to.heading - from.heading));
      view.root.position.set(
        from.x + (to.x - from.x) * t,
        from.y + (to.y - from.y) * t,
        from.z + (to.z - from.z) * t,
      );
      view.root.rotation.set(
        from.pitch + (to.pitch - from.pitch) * t,
        from.heading + angle * t,
        0,
      );
    }
  }

  function dispose(): void {
    disposed = true;
    latest.clear();
    for (const id of [...views.keys()]) disposeView(id);
    for (const container of containers.values()) container.dispose();
    containers.clear();
    neededModels.clear();
    for (const request of loading.values()) request.controller.abort();
    loading.clear();
  }

  scene.onDisposeObservable.addOnce(dispose);
  function stats() {
    return { states: latest.size, instances: views.size, models: containers.size, pending: loading.size };
  }
  return { handleSnapshot, setEnabled, update, dispose, stats };
}
