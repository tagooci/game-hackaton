import { VEHICLE_PAINTS } from '../vehicle/vehiclePaint';
import { VertexBuffer } from '@babylonjs/core/Buffers/buffer.js';
import "@babylonjs/loaders/glTF/2.0/glTFLoader.js";
import { Engine } from "@babylonjs/core/Engines/engine.js";
import { Scene } from "@babylonjs/core/scene.js";
import { ArcRotateCamera } from "@babylonjs/core/Cameras/arcRotateCamera.js";
import { HemisphericLight } from "@babylonjs/core/Lights/hemisphericLight.js";
import { DirectionalLight } from "@babylonjs/core/Lights/directionalLight.js";
import { Vector3 } from "@babylonjs/core/Maths/math.vector.js";
import { Color3, Color4 } from "@babylonjs/core/Maths/math.color.js";
import { Texture } from "@babylonjs/core/Materials/Textures/texture.js";
import { TransformNode } from "@babylonjs/core/Meshes/transformNode.js";
import { MeshBuilder } from "@babylonjs/core/Meshes/meshBuilder.js";
import { StandardMaterial } from "@babylonjs/core/Materials/standardMaterial.js";
import { LoadAssetContainerAsync } from "@babylonjs/core/Loading/sceneLoader.js";

// Rendering and markup behavior preserved from frontend/pages/menu.html.
export function mountMenuPreview(root, color, model, sportsUnlocked, onStart) {


  const canvas = root.querySelector("#preview");
  const status = root.querySelector("#status");

  const engine = new Engine(canvas, true, {
    preserveDrawingBuffer: true,
    stencil: true
  });

  const scene = new Scene(engine);
  scene.clearColor = new Color4(242/255, 228/255, 213/255, 1);

  const camera = new ArcRotateCamera(
    "preview-camera",
    -Math.PI / 2.2,
    Math.PI / 2.8,
    8,
    new Vector3(0, 0.8, 0),
    scene
  );
  camera.lowerRadiusLimit = 5;
  camera.upperRadiusLimit = 12;
  camera.attachControl(canvas, true);

  const hemi = new HemisphericLight(
    "preview-hemi",
    new Vector3(0, 1, 0),
    scene
  );
  hemi.intensity = 0.9;

  const keyLight = new DirectionalLight(
    "preview-key",
    new Vector3(-1, -2, 1),
    scene
  );
  keyLight.position = new Vector3(4, 8, -4);
  keyLight.intensity = 1.2;

  let selectedColor = color;
  let selectedModel = model;
  let modelRoot = null;
  let currentContainer = null;
  let loadId = 0;

  function showError(message, error) {
    console.error(message, error);
    status.textContent = message;
  }

  function createFallbackRoad() {
    const material = new StandardMaterial("road-fallback-material", scene);
    material.diffuseColor = new Color3(0.16, 0.17, 0.17);

    const road = MeshBuilder.CreateGround(
      "road-fallback",
      { width: 4.2, height: 4.6 },
      scene
    );

    road.position.y = -0.06;
    road.material = material;
  }

  async function loadRoad() {
    try {
      const road = await LoadAssetContainerAsync(
        "/assets/menu/models/road/road-straight.glb",
        scene,
        { pluginExtension: ".glb" }
      );

      if (scene.isDisposed) { road.dispose(); return; }
      road.addAllToScene();

      const roadRoot = new TransformNode("road-root", scene);
      for (const node of road.rootNodes) {
        node.parent = roadRoot;
      }

      const { min, max } = roadRoot.getHierarchyBoundingVectors(true);
      const sx = 4.2 / (max.x - min.x);
      const sz = 4.6 / (max.z - min.z);
      roadRoot.scaling.set(sx, 1, sz);
      roadRoot.position.set(-(min.x + max.x) * sx / 2, -max.y - 0.015, -(min.z + max.z) * sz / 2);
    } catch (error) {
      showError("Дорога не загрузилась; показываю временную площадку.", error);
      createFallbackRoad();
    }
  }

  const paintTexture = new Texture('/assets/car-kit/Textures/colormap.png', scene, false, false, Texture.NEAREST_SAMPLINGMODE);
  function recolorVehicle(root) {
    const paint = VEHICLE_PAINTS.find(paint => paint.color === selectedColor);
    for (const mesh of root.getChildMeshes()) {
      if (!/-(body|spoiler)$/.test(mesh.name) || !mesh.material || !paint) continue;
      if (!mesh.metadata?.paintUVs) {
        mesh.makeGeometryUnique();
        mesh.metadata = { ...mesh.metadata, paintUVs: Array.from(mesh.getVerticesData(VertexBuffer.UVKind)) };
        mesh.material = mesh.material.clone(`${mesh.name}-paint`);
        mesh.material.albedoColor = Color3.White();
        mesh.material.albedoTexture = paintTexture;
      }
      const uvs = mesh.metadata.paintUVs.slice();
      for (let i=0; i<uvs.length; i+=2) {
        if (Math.abs(uvs[i]-.84375)<.001 && uvs[i+1]<.5) uvs[i]=paint.u;
      }
      mesh.setVerticesData(VertexBuffer.UVKind, uvs);
    }
  }

  async function loadVehicle(model) {
    const thisLoad = ++loadId;
    status.textContent = "Загружаю машину…";

    modelRoot?.dispose();
    modelRoot = null;
    currentContainer?.dispose();
    currentContainer = null;

    const url = model === "sedan"
      ? "/assets/menu/models/sedan/model.glb"
      : "/assets/menu/models/sedan-sports/model.glb";

    try {
      const container = await LoadAssetContainerAsync(
        url,
        scene,
        { pluginExtension: ".glb" }
      );

      if (thisLoad !== loadId) {
        container.dispose();
        return;
      }

      currentContainer = container;

      const instance = container.instantiateModelsToScene(
        name => `preview-${name}`, true, { doNotInstantiate: true }
      );

      modelRoot = new TransformNode("preview-car-root", scene);

      const centeredModel = new TransformNode("centered-model", scene);
      for (const node of instance.rootNodes) node.parent = centeredModel;
      const bounds = centeredModel.getHierarchyBoundingVectors(true);
      const size = bounds.max.subtract(bounds.min);
      const largest = Math.max(size.x, size.y, size.z);

      if (!Number.isFinite(largest) || largest <= 0) {
        throw new Error("У модели не получилось определить размеры.");
      }

      const scale = 3.4 / largest;
      centeredModel.scaling.setAll(scale);
      centeredModel.position.set(-(bounds.min.x + bounds.max.x) * scale / 2, -bounds.min.y * scale, -(bounds.min.z + bounds.max.z) * scale / 2);
      centeredModel.parent = modelRoot;
      modelRoot.rotation.y = Math.PI;

      recolorVehicle(modelRoot);

      status.textContent = "";
    } catch (error) {
      showError(`Не загрузилась модель: ${url}`, error);
    }
  }

  root.querySelectorAll(".color-option:not(:disabled)").forEach(button => {
    button.addEventListener("click", () => {
      selectedColor = button.dataset.color;

      root.querySelectorAll(".color-option:not(:disabled)").forEach(option => {
        option.setAttribute("aria-pressed", String(option === button));
      });

      if (modelRoot) recolorVehicle(modelRoot);
    });
  });

  root.querySelectorAll(".car-option").forEach(button => {
    button.addEventListener("click", () => {
      root.querySelectorAll(".car-option").forEach(option => {
        option.setAttribute("aria-pressed", String(option === button));
      });

      selectedModel = button.dataset.model;
      loadVehicle(selectedModel);
    });
  });

  root.querySelector(".go-button").addEventListener("click", () => {
    const button = root.querySelector('.go-button');
    button.disabled = true;
    Promise.resolve(onStart(selectedColor, selectedModel)).catch(error => {
      showError(error.message, error); button.disabled = false;
    });
  });

  scene.onBeforeRenderObservable.add(() => {
    if (modelRoot) {
      modelRoot.rotation.y += engine.getDeltaTime() * 0.00012;
    }
  });

  engine.runRenderLoop(() => scene.render());
  const resize = () => engine.resize();
  window.addEventListener("resize", resize);

  root.querySelectorAll('.color-option[data-color]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.color===selectedColor)));
  root.querySelectorAll('.car-option').forEach(button => {
    button.setAttribute('aria-pressed',String(button.dataset.model===selectedModel));
    if (button.dataset.model==='sports' && !sportsUnlocked) button.disabled=true;
  });
  void (async () => { await loadRoad(); if (!scene.isDisposed) await loadVehicle(selectedModel); })();
  return () => {
    loadId++;
    window.removeEventListener('resize',resize);
    engine.stopRenderLoop(); scene.dispose(); engine.dispose();
  };

}
