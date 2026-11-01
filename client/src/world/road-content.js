import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader.js';
import { Matrix, Quaternion, Vector3 } from '@babylonjs/core/Maths/math.vector.js';
import { Mesh } from '@babylonjs/core/Meshes/mesh.js';
import '@babylonjs/core/Meshes/thinInstanceMesh.js';
import '@babylonjs/loaders/glTF/2.0/glTFLoader.js';
import '@babylonjs/loaders/glTF/2.0/Extensions/KHR_mesh_quantization.js';

// Локальный адаптер просмотра карты. В игровой v2 план выбирает сервер.
// Файлы мира всегда запрашиваются без HTTP/постоянного кеша.
export class RoadContent {
  constructor(scene, onStatus) {
    this.scene = scene;
    this.onStatus = onStatus;
    this.loaded = new Map();
    this.residentResources = [];
    this.fixedBytes = 0;
    this.reserved = 0;
    this.rendered = [];
    this.groups = new Map();
    this.activeHashes = new Set();
    this.activeObjects = [];
    this.activeKey = "";
    this.planKey = '';
    this.serial = Promise.resolve();
    this.revision = 0;
    this.disposed = false;
  }

  async init(manifestUrl = '/content/world/manifest.json') {
    const response = await fetch(manifestUrl, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Манифест: HTTP ${response.status}`);
    const data = await response.arrayBuffer();
    this.manifest = JSON.parse(new TextDecoder().decode(data));
    this.residentResources = [...this.manifest.residentResources,
      { id: 'world-manifest', kind: 'data', bytes: data.byteLength }];
    this.fixedBytes = this.residentResources.reduce((sum, resource) => sum + resource.bytes, 0);
    this.registry = new Map(this.manifest.resources.map(resource => [resource.id, resource]));
    this.budget = this.manifest.cacheBudgetBytes;
    const resource = this.registry.get(this.manifest.overviewResourceId);
    this.overview = (await this.acquire(resource)).value;
    return this.manifest;
  }

  report(extra = {}) {
    const active = this.fixedBytes + [...this.loaded.values()].reduce((sum, entry) => sum + entry.resource.bytes, 0);
    this.onStatus({ active, reserved: this.reserved, budget: this.budget,
      worldBytes: this.manifest.worldBytes, resources: this.loaded.size, ...extra });
  }

  async acquire(resource) {
    const cached = this.loaded.get(resource.sha256);
    if (cached) return cached;
    const used = this.fixedBytes + [...this.loaded.values()].reduce((sum, entry) => sum + entry.resource.bytes, 0);
    if (used + this.reserved + resource.bytes > this.budget) {
      throw new Error(`budget_exceeded: ${resource.id}`);
    }
    this.reserved += resource.bytes;
    this.report({ loading: resource.id });
    let container;
    try {
      const response = await fetch(resource.url, { cache: 'no-store' });
      if (!response.ok) throw new Error(`${resource.id}: HTTP ${response.status}`);
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength !== resource.bytes) throw new Error(`resource_mismatch: ${resource.id}`);
      // SHA проверяется локально и при LAN HTTP, где crypto.subtle недоступен.
      const { sha256 } = await import('./sha256.js');
      if (sha256(new Uint8Array(buffer)) !== resource.sha256) throw new Error(`resource_mismatch: ${resource.id}`);
      const decoded = resource.encoding === 'gzip'
        ? await new Response(new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer()
        : buffer;
      let value;
      if (resource.kind === 'model') {
        container = await LoadAssetContainerAsync(new Uint8Array(decoded), this.scene, { pluginExtension: '.glb' });
        value = container;
      } else value = JSON.parse(new TextDecoder().decode(decoded));
      if (this.disposed) { container?.dispose(); throw new Error('scene_disposed'); }
      const entry = { resource, value };
      this.loaded.set(resource.sha256, entry);
      return entry;
    } catch (error) {
      container?.dispose();
      throw error;
    } finally {
      this.reserved -= resource.bytes;
      this.report();
    }
  }

  stats() {
    const resources = [...this.residentResources, ...[...this.loaded.values()].map(({ resource }) => ({ id: resource.id, bytes: resource.bytes, kind: resource.kind }))];
    return {
      chunk: this.activeKey, requestedChunk: this.planKey, resources,
      activeBytes: resources.reduce((sum, resource) => sum + resource.bytes, 0),
      reservedBytes: this.reserved, budgetBytes: this.budget,
      meshes: this.rendered.length,
    };
  }

  releaseUnused(hashes) {
    for (const [hash, entry] of this.loaded) if (!hashes.has(hash)) {
      if (entry.resource.kind === 'model') entry.value.dispose();
      this.loaded.delete(hash);
    }
  }

  clearMeshes() {
    for (const mesh of this.rendered) mesh.dispose(false, false);
    this.rendered = [];
    this.groups.clear();
  }

  matrices(objects) {
    const matrices = new Float32Array(objects.length * 16);
    objects.forEach((object, index) => {
      if (object.matrix) { matrices.set(object.matrix, index * 16); return; }
      Matrix.Compose(Array.isArray(object.scale) ? Vector3.FromArray(object.scale) : new Vector3(object.scale, object.scale, object.scale),
        Quaternion.FromEulerAngles(0, object.heading, 0),
        new Vector3(object.x, object.y ?? (object.reference ? 0 : -0.1), object.z)).copyToArray(matrices, index * 16);
    });
    return matrices;
  }

  // До загрузки освобождаем только участки за дальностью видимости.
  // Видимая часть дороги остаётся на экране даже при ошибке сети.
  trimDistant(chunkIds) {
    this.activeObjects = this.activeObjects.filter(object => !object.chunkId || chunkIds.has(object.chunkId));
    const hashes = new Set([this.registry.get(this.manifest.overviewResourceId).sha256]);
    for (const object of this.activeObjects) {
      hashes.add(this.registry.get(object.assetId).sha256);
      if (object.chunkId) hashes.add(this.registry.get(object.chunkId).sha256);
    }
    for (const [id, meshes] of this.groups) {
      const objects = this.activeObjects.filter(object => object.assetId === id);
      if (!objects.length) {
        for (const mesh of meshes) mesh.dispose(false, false);
        this.groups.delete(id);
      } else for (const mesh of meshes) {
        mesh.thinInstanceSetBuffer('matrix', this.matrices(objects), 16, true);
        mesh.thinInstanceRefreshBoundingInfo(true);
      }
    }
    this.rendered = [...this.groups.values()].flat();
    this.activeHashes = hashes;
    this.releaseUnused(hashes);
  }

  // Очередь не допускает одновременных резервов двух планов.
  // Устаревший результат не создаёт объекты новой области.
  update(x, z, force = false) {
    if (this.disposed) return this.serial;
    const step = this.manifest.streamStep ?? this.manifest.chunkSize;
    const key = `${Math.floor(x/step)}:${Math.floor(z/step)}:${this.vehicleType ?? 'none'}`;
    if (!force && key === this.planKey) return this.serial;
    this.planKey = key;
    const revision = ++this.revision;
    this.serial = this.serial.catch(() => {}).then(async () => {
      if (revision !== this.revision) return;
      const radius = this.manifest.streamRadius ?? this.manifest.chunkSize;
      const chunks = this.manifest.chunks.filter(({bounds:b}) =>
        Math.hypot(Math.max(b.minX-x, 0, x-b.maxX), Math.max(b.minZ-z, 0, z-b.maxZ)) < radius);
      const ids = new Set([this.manifest.overviewResourceId]);
      if (this.vehicleType) ids.add(this.manifest.vehicleReference[this.vehicleType].assetId);
      for (const chunk of chunks) for (const id of [chunk.resourceId, ...chunk.assetIds]) ids.add(id);
      const unique = new Map([...ids].map(id => { const r=this.registry.get(id); return [r.sha256,r]; }));
      const cost = this.fixedBytes + [...unique.values()].reduce((sum,r)=>sum+r.bytes,0);
      if (cost > this.budget) { this.planKey='';throw new Error('budget_exceeded'); }
      // Исключённые из нового круга участки уже дальше streamRadius.
      this.trimDistant(new Set(chunks.map(chunk => chunk.resourceId)));
      const resources = [...ids].map(id => this.registry.get(id));
      this.report({ transitioning: true });
      // Старые meshes и контейнеры остаются видимыми до готовности новой области.
      const hashes = new Set(resources.map(r => r.sha256));
      for (const resource of resources) {
        if (revision !== this.revision) return;
        await this.acquire(resource);
      }
      if (revision !== this.revision) return;
      const objects = [];
      for (const chunk of chunks) {
        const data = this.loaded.get(this.registry.get(chunk.resourceId).sha256).value;
        objects.push(...data.objects.map(object => ({ ...object, chunkId: chunk.resourceId })));
        for (const sign of data.signs) objects.push({ ...sign,
          chunkId: chunk.resourceId, assetId: sign.type === 'stop' ? 'road-sign-stop' : 'traffic-light', scale: 4 });
      }
      if (this.vehicleType) {
        const reference = this.manifest.vehicleReference[this.vehicleType];
        objects.push({ id:'reference-vehicle', assetId:reference.assetId, x, z, heading:Math.PI/2, scale:1, reference });
      }
      const groups = new Map();
      for (const object of objects) {
        if (!groups.has(object.assetId)) groups.set(object.assetId, []);
        groups.get(object.assetId).push(object);
      }
      const staged = new Map();
      const created = [];
      try {
        for (const [id, instances] of groups) {
          const container = this.loaded.get(this.registry.get(id).sha256).value;
          const sourceMeshes = container.meshes.filter(mesh => mesh.getTotalVertices() > 0);
          let normalization = Matrix.Identity();
          const reference = instances[0].reference;
          if (reference) {
            const min = new Vector3(Infinity,Infinity,Infinity), max = new Vector3(-Infinity,-Infinity,-Infinity);
            for (const source of sourceMeshes) {
              source.computeWorldMatrix(true);
              min.minimizeInPlace(source.getBoundingInfo().boundingBox.minimumWorld);
              max.maximizeInPlace(source.getBoundingInfo().boundingBox.maximumWorld);
            }
            normalization = Matrix.Translation(-(min.x+max.x)/2,-min.y,-(min.z+max.z)/2)
              .multiply(Matrix.Scaling(reference.width/(max.x-min.x),reference.height/(max.y-min.y),reference.length/(max.z-min.z)));
          }
          for (const source of sourceMeshes) {
            source.computeWorldMatrix(true);
            const existing = this.groups.get(id)?.find(mesh => mesh.metadata.sourceId === source.uniqueId);
            const mesh = existing ?? new Mesh(`roads:${id}`, this.scene);
            if (!existing) {
              mesh.setEnabled(false);
              mesh.metadata = { sourceId: source.uniqueId };
              created.push(mesh);
              for (const kind of source.getVerticesDataKinds()) {
                const buffer = source.getVertexBuffer(kind);
                // Квантизованные нормали/цвета нужно декодировать перед впеканием.
                mesh.setVerticesData(kind, buffer.getFloatData(source.getTotalVertices(), true));
              }
              // bakeTransformIntoVertices меняет winding при зеркальном импорте glTF.
              // Индексы должны быть собственной копией, ориентация — как у источника.
              mesh.setIndices(source.getIndices().slice());
              mesh.sideOrientation = source.sideOrientation;
              mesh.material = source.material;
              mesh.receiveShadows = true;
              // Впекаем только преобразование импорта: оси glTF и деквантизацию.
              mesh.bakeTransformIntoVertices(source.getWorldMatrix().multiply(normalization));
            }
            const matrices = this.matrices(instances);
            if (!existing) mesh.thinInstanceSetBuffer('matrix', matrices, 16, true);
            if (!staged.has(id)) staged.set(id, []);
            staged.get(id).push({ mesh, matrices });
          }
        }
        // Подготавливаем шейдеры новых типов дорог, не скрывая текущие.
        await Promise.all(created.map(mesh => mesh.material.forceCompilationAsync(mesh, { useInstances: true })));
        if (revision !== this.revision) {
          for (const mesh of created) mesh.dispose(false, false);
          this.releaseUnused(this.activeHashes);
          return;
        }
        // Один синхронный обмен: общая геометрия сохраняется, меняются только матрицы.
        for (const entries of staged.values()) for (const { mesh, matrices } of entries) {
          mesh.thinInstanceSetBuffer('matrix', matrices, 16, true);
          mesh.thinInstanceRefreshBoundingInfo(true);
          mesh.setEnabled(true);
        }
        for (const [id, meshes] of this.groups) if (!staged.has(id)) {
          for (const mesh of meshes) mesh.dispose(false, false);
        }
        this.groups = new Map([...staged].map(([id, entries]) => [id, entries.map(entry => entry.mesh)]));
        this.rendered = [...this.groups.values()].flat();
        this.activeKey = key;
        this.activeObjects = objects;
        this.activeHashes = hashes;
        this.releaseUnused(hashes);
      } catch (error) {
        for (const mesh of created) mesh.dispose(false, false);
        throw error;
      }
      this.report({ ready: true, transitioning: false, chunks: chunks.length, objects: objects.length });
    });
    this.serial = this.serial.catch(error => {
      this.releaseUnused(this.activeHashes);
      if (revision === this.revision) this.planKey = '';
      throw error;
    });
    return this.serial;
  }

  dispose() {
    this.disposed = true;
    this.revision++;
    this.clearMeshes();
    this.serial.catch(() => {}).then(() => {
      for (const entry of this.loaded.values()) {
        if (entry.resource.kind === 'model') entry.value.dispose();
      }
      this.loaded.clear();
    });
  }
}
