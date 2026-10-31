import '@babylonjs/loaders/glTF/2.0/glTFLoader.js';
import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader.js';
import { VertexBuffer } from '@babylonjs/core/Buffers/buffer.js';
import { Quaternion, Vector3 } from '@babylonjs/core/Maths/math.vector.js';
import type { Mesh } from '@babylonjs/core/Meshes/mesh.js';
import { TransformNode } from '@babylonjs/core/Meshes/transformNode.js';
import type { AssetContainer, InstantiatedEntries } from '@babylonjs/core/assetContainer.js';
import type { Scene } from '@babylonjs/core/scene.js';

export const VEHICLE_LENGTH = 3.3;

export interface VehiclePose {
  x: number;
  z: number;
  heading: number;
  y?: number;
  pitch?: number;
  wheelAngle?: number;
  color?: number;
}

// Одна загрузка на сцену; текстура и материалы общие для всех машин.
const models = new WeakMap<Scene, Promise<AssetContainer>>();

function loadModel(scene: Scene): Promise<AssetContainer> {
  let model = models.get(scene);
  if (!model) {
    model = LoadAssetContainerAsync(`${import.meta.env.BASE_URL}assets/car-kit/sedan.glb`, scene)
      .then(container => {
        if (scene.isDisposed) container.dispose();
        else scene.onDisposeObservable.addOnce(() => container.dispose());
        return container;
      });
    models.set(scene, model);
  }
  return model;
}

/** Только отображение. Координаты машины рассчитывает физика, а не камера. */
export function createVehicleView(scene: Scene, length: number, name = 'local-vehicle') {
  // Начало координат — центр основания на земле, как в протоколе v2.
  const root = new TransformNode(name, scene);
  // Отдельная точка, за которой следит камера.
  const body = new TransformNode(`${name}-camera-target`, scene);
  body.parent = root;
  let instance: InstantiatedEntries | undefined;
  let wheelAngle = 0;
  let color = 3; // До первого snapshot — исходный красный кузов.
  let paintMesh: Mesh | undefined;
  let originalUVs: number[] | undefined;
  const frontWheels: Mesh[] = [];

  function updateAppearance(): void {
    if (!paintMesh || !originalUVs) return;
    const uvs = originalUVs.slice();
    for (let i = 0; i < uvs.length; i += 2) {
      // В sedan.glb красный кузов использует этот столбец палитры.
      // Нижние серые участки той же колонки оставляем без изменений.
      if (Math.abs(uvs[i] - 0.84375) < 0.001 && uvs[i + 1] < 0.5) {
        uvs[i] = 0.46875 + color * 0.125;
      }
    }
    paintMesh.setVerticesData(VertexBuffer.UVKind, uvs);
  }

  const ready = loadModel(scene)
    .then(container => {
      if (root.isDisposed()) return;
      instance = container.instantiateModelsToScene(meshName => `${name}-${meshName}`, false, { doNotInstantiate: true });
      const model = new TransformNode(`${name}-model`, scene);
      for (const node of instance.rootNodes) node.parent = model;
      for (const mesh of model.getChildMeshes()) {
        if (mesh.name === `${name}-body`) {
          paintMesh = mesh as Mesh;
          paintMesh.makeGeometryUnique();
          originalUVs = Array.from(paintMesh.getVerticesData(VertexBuffer.UVKind)!);
        }
        if (mesh.name.includes('wheel-front-')) {
          const wheel = mesh as Mesh;
          wheel.setPivotPoint(wheel.getBoundingInfo().boundingBox.center);
          frontWheels.push(wheel);
        }
      }
      updateAppearance();
      // Знак учитывает преобразование glTF в левую систему координат Babylon.
      for (const wheel of frontWheels) wheel.rotationQuaternion = Quaternion.RotationAxis(Vector3.Up(), -wheelAngle);
      // Сохраняем пропорции, ставим колёса на землю и центрируем кузов.
      const { min, max } = model.getHierarchyBoundingVectors(true);
      const scale = length / (max.z - min.z);
      model.scaling.setAll(scale);
      model.position.set(-(min.x + max.x) * scale / 2, -min.y * scale, -(min.z + max.z) * scale / 2);
      model.parent = root;
      body.position.y = (max.y - min.y) * scale / 2;
    });
  ready.catch(error => console.error('Не удалось загрузить модель машины:', error));

  function setPose(pose: VehiclePose): void {
    root.position.set(pose.x, pose.y ?? 0, pose.z);
    root.rotation.x = pose.pitch ?? 0;
    root.rotation.y = pose.heading;
    const nextAngle = pose.wheelAngle ?? wheelAngle;
    const nextColor = pose.color ?? color;
    if (nextAngle !== wheelAngle || nextColor !== color) {
      const colorChanged = nextColor !== color;
      wheelAngle = nextAngle;
      color = nextColor;
      // Знак учитывает преобразование glTF в левую систему координат Babylon.
      for (const wheel of frontWheels) wheel.rotationQuaternion = Quaternion.RotationAxis(Vector3.Up(), -wheelAngle);
      if (colorChanged) updateAppearance();
    }
  }

  function getPose(): VehiclePose {
    return { x: root.position.x, y: root.position.y, pitch: root.rotation.x, z: root.position.z, heading: root.rotation.y, wheelAngle, color };
  }

  function dispose(): void {
    root.dispose();
    instance?.dispose();
  }

  return { root, body, ready, setPose, getPose, dispose };
}
