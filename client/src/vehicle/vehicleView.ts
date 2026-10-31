import '@babylonjs/loaders/glTF/2.0/glTFLoader.js';
import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader.js';
import { TransformNode } from '@babylonjs/core/Meshes/transformNode.js';
import type { AssetContainer, InstantiatedEntries } from '@babylonjs/core/assetContainer.js';
import type { Scene } from '@babylonjs/core/scene.js';

export interface VehiclePose {
  x: number;
  z: number;
  heading: number;
}

// Одна загрузка на сцену; машины используют общую геометрию и материалы.
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

  const ready = loadModel(scene)
    .then(container => {
      if (root.isDisposed()) return;
      instance = container.instantiateModelsToScene(meshName => `${name}-${meshName}`, false);
      const model = new TransformNode(`${name}-model`, scene);
      for (const node of instance.rootNodes) node.parent = model;
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
    root.position.set(pose.x, 0, pose.z);
    root.rotation.y = pose.heading;
  }

  function getPose(): VehiclePose {
    return { x: root.position.x, z: root.position.z, heading: root.rotation.y };
  }

  function dispose(): void {
    root.dispose();
    instance?.dispose();
  }

  return { root, body, ready, setPose, getPose, dispose };
}
