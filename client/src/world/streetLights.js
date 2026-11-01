import { Color3 } from '@babylonjs/core/Maths/math.color.js';
import { Matrix, Quaternion, Vector3 } from '@babylonjs/core/Maths/math.vector.js';
import { SpotLight } from '@babylonjs/core/Lights/spotLight.js';

// Separate lens geometry from the imported map, shared by its thin instances.
const LENS_ASSET = 'map-d8fe3b88f5aa4e92';

export function createStreetLights(scene, roads) {
  const lights = Array.from({ length: 2 }, (_, i) => {
    const light = new SpotLight(`street-lamp-${i}`, Vector3.Zero(), Vector3.Down(), Math.PI * 0.8, 2, scene);
    light.diffuse = new Color3(1, 0.78, 0.45);
    light.specular = new Color3(0.35, 0.25, 0.12);
    light.intensity = 3;
    light.range = 22;
    light.setEnabled(false);
    return light;
  });
  let night = false;
  let lastUpdate = -Infinity;
  const originalEmission = new WeakMap();

  function update(x, z) {
    if (!night || performance.now() - lastUpdate < 250) return;
    lastUpdate = performance.now();
    const resource = roads.registry?.get(LENS_ASSET);
    const container = resource && roads.loaded.get(resource.sha256)?.value;
    if (!container) {
      lights.forEach(light => light.setEnabled(false));
      return;
    }
    const min = new Vector3(Infinity, Infinity, Infinity);
    const max = new Vector3(-Infinity, -Infinity, -Infinity);
    for (const mesh of container.meshes) {
      if (!mesh.getTotalVertices()) continue;
      mesh.computeWorldMatrix(true);
      const box = mesh.getBoundingInfo().boundingBox;
      min.minimizeInPlace(box.minimumWorld);
      max.maximizeInPlace(box.maximumWorld);
      const material = mesh.material;
      if (material?.emissiveColor) {
        if (!originalEmission.has(material)) originalEmission.set(material, material.emissiveColor.clone());
        material.emissiveColor.set(1, 0.78, 0.45);
      }
    }
    if (!Number.isFinite(min.x)) return;
    const center = min.add(max).scale(0.5);
    const positions = roads.activeObjects.filter(object => object.assetId === LENS_ASSET).map(object => {
      const matrix = object.matrix ? Matrix.FromArray(object.matrix) : Matrix.Compose(
        Array.isArray(object.scale) ? Vector3.FromArray(object.scale) : Vector3.One().scale(object.scale ?? 1),
        Quaternion.FromEulerAngles(0, object.heading ?? 0, 0),
        new Vector3(object.x, object.y ?? 0, object.z));
      return Vector3.TransformCoordinates(center, matrix);
    }).filter(position => Math.hypot(position.x - x, position.z - z) < 35)
      .sort((a, b) => Math.hypot(a.x - x, a.z - z) - Math.hypot(b.x - x, b.z - z));
    lights.forEach((light, i) => {
      const position = positions[i];
      light.setEnabled(!!position);
      if (position) light.position.copyFrom(position).addInPlaceFromFloats(0, -0.08, 0);
    });
  }

  return {
    update,
    setNight(value) {
      night = value;
      lastUpdate = -Infinity;
      lights.forEach(light => light.setEnabled(false));
      if (!night) for (const entry of roads.loaded.values()) {
        if (entry.resource.id !== LENS_ASSET) continue;
        for (const mesh of entry.value.meshes) {
          const material = mesh.material;
          const original = material && originalEmission.get(material);
          if (original) material.emissiveColor.copyFrom(original);
        }
      }
    },
    dispose() { lights.forEach(light => light.dispose()); },
  };
}
