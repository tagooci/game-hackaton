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
    this.reserved = 0;
    this.rendered = [];
    this.planKey = '';
    this.serial = Promise.resolve();
    this.revision = 0;
    this.disposed = false;
  }

  async init(manifestUrl = '/content/world/manifest.json') {
    const response = await fetch(manifestUrl, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Манифест: HTTP ${response.status}`);
    this.manifest = await response.json();
    this.registry = new Map(this.manifest.resources.map(resource => [resource.id, resource]));
    this.budget = this.manifest.cacheBudgetBytes;
    const resource = this.registry.get(this.manifest.overviewResourceId);
    this.overview = (await this.acquire(resource)).value;
    return this.manifest;
  }

  report(extra = {}) {
    const active = [...this.loaded.values()].reduce((sum, entry) => sum + entry.resource.bytes, 0);
    this.onStatus({ active, reserved: this.reserved, budget: this.budget,
      worldBytes: this.manifest.worldBytes, resources: this.loaded.size, ...extra });
  }

  async acquire(resource) {
    const cached = this.loaded.get(resource.sha256);
    if (cached) return cached;
    const used = [...this.loaded.values()].reduce((sum, entry) => sum + entry.resource.bytes, 0);
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
      let value;
      if (resource.kind === 'model') {
        container = await LoadAssetContainerAsync(new Uint8Array(buffer), this.scene, { pluginExtension: '.glb' });
        value = container;
      } else value = JSON.parse(new TextDecoder().decode(buffer));
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

  clearMeshes() {
    for (const mesh of this.rendered) mesh.dispose(false, false);
    this.rendered = [];
  }

  // Очередь не допускает одновременных резервов двух планов.
  // Устаревший результат не создаёт объекты новой области.
  update(x, z, force = false) {
    if (this.disposed) return this.serial;
    const cx = Math.floor(x / this.manifest.chunkSize);
    const cz = Math.floor(z / this.manifest.chunkSize);
    const key = `${cx}:${cz}:${this.vehicleType ?? 'none'}`;
    if (!force && key === this.planKey) return this.serial;
    this.planKey = key;
    const revision = ++this.revision;
    this.serial = this.serial.catch(() => {}).then(async () => {
      if (revision !== this.revision) return;
      const size = this.manifest.chunkSize;
      // Минимальная соседняя порция: текущий участок и ближайшие дороги.
      // Если сумма не помещается, план отклоняется, лимит не увеличивается.
      const candidates = this.manifest.chunks.filter(chunk =>
        chunk.bounds.maxX > cx * size - size && chunk.bounds.minX < (cx + 1) * size + size &&
        chunk.bounds.maxZ > cz * size - size && chunk.bounds.minZ < (cz + 1) * size + size)
        .sort((a,b) => {
          const distance = c => Math.hypot((c.bounds.minX+c.bounds.maxX)/2-x,(c.bounds.minZ+c.bounds.maxZ)/2-z);
          // Участок под камерой обязателен, соседи добавляются по расстоянию.
          const contains = c => x>=c.bounds.minX && x<c.bounds.maxX && z>=c.bounds.minZ && z<c.bounds.maxZ;
          return Number(contains(b))-Number(contains(a)) || distance(a)-distance(b);
        });
      const ids = new Set([this.manifest.overviewResourceId]);
      if (this.vehicleType) ids.add(this.manifest.vehicleReference[this.vehicleType].assetId);
      const chunks = [];
      const cost = ids => [...new Map([...ids].map(id => { const r=this.registry.get(id); return [r.sha256,r]; })).values()].reduce((sum,r)=>sum+r.bytes,0);
      for (const chunk of candidates) {
        const proposed = new Set([...ids,chunk.resourceId,...chunk.assetIds]);
        if (cost(proposed)>this.budget) {
          if (!chunks.length) { this.planKey='';throw new Error('budget_exceeded'); }
          continue;
        }
        chunks.push(chunk);
        for (const id of proposed) ids.add(id);
      }
      const resources = [...ids].map(id => this.registry.get(id));
      this.report({ transitioning: true });
      // В авторском просмотре допустим переход через экран загрузки:
      // сначала освобождаем старые ресурсы, затем резервируем новые.
      this.clearMeshes();
      const hashes = new Set(resources.map(r => r.sha256));
      for (const [hash, entry] of this.loaded) if (!hashes.has(hash)) {
        if (entry.resource.kind === 'model') entry.value.dispose();
        this.loaded.delete(hash);
      }
      for (const resource of resources) {
        if (revision !== this.revision) return;
        await this.acquire(resource);
      }
      if (revision !== this.revision) return;
      const objects = [];
      for (const chunk of chunks) {
        const data = this.loaded.get(this.registry.get(chunk.resourceId).sha256).value;
        objects.push(...data.objects);
        for (const sign of data.signs) objects.push({ ...sign,
          assetId: sign.type === 'stop' ? 'road-sign-stop' : 'traffic-light', scale: 4 });
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
          const mesh = new Mesh(`roads:${id}`, this.scene);
          for (const kind of source.getVerticesDataKinds()) {
            const buffer = source.getVertexBuffer(kind);
            // Квантизованные нормали/цвета нужно декодировать перед впеканием.
            mesh.setVerticesData(kind, buffer.getFloatData(source.getTotalVertices(), true));
          }
          mesh.setIndices(source.getIndices());
          mesh.material = source.material;
          // Впекаем только преобразование импорта: оси glTF и деквантизацию.
          mesh.bakeTransformIntoVertices(source.getWorldMatrix().multiply(normalization));
          const matrices = new Float32Array(instances.length * 16);
          instances.forEach((object, index) => {
            Matrix.Compose(new Vector3(object.scale, object.scale, object.scale),
              Quaternion.FromEulerAngles(0, object.heading, 0),
              new Vector3(object.x, object.reference ? 0 : -0.1, object.z)).copyToArray(matrices, index * 16);
          });
          mesh.thinInstanceSetBuffer('matrix', matrices, 16, true);
          mesh.thinInstanceRefreshBoundingInfo(true);
          this.rendered.push(mesh);
        }
      }
      this.report({ ready: true, transitioning: false, chunks: chunks.length, objects: objects.length });
    });
    this.serial = this.serial.catch(error => {
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
