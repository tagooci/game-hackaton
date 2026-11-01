// Separate lens geometry from the imported map, shared by its thin instances.
const LENS_ASSET = 'map-d8fe3b88f5aa4e92';
const isLens = mesh => mesh.name === LENS_ASSET || /lamp[ _-]*lens/i.test(mesh.name);

export function createStreetLights(roads) {
  let night = false;
  let lastUpdate = -Infinity;
  const originalEmission = new WeakMap();

  function update() {
    if (!night || performance.now() - lastUpdate < 250) return;
    lastUpdate = performance.now();
    const resource = roads.registry?.get(LENS_ASSET);
    const container = resource && roads.loaded.get(resource.sha256)?.value;
    if (!container) return;
    for (const mesh of container.meshes) {
      if (!mesh.getTotalVertices() || !isLens(mesh)) continue;
      // The imported file shares its material with unrelated road geometry.
      // Give only the lens its own emissive material, including streamed instances.
      if (mesh.material?.emissiveColor && !originalEmission.has(mesh.material)) {
        const material = mesh.material.clone('street-lamp-lens');
        originalEmission.set(material, material.emissiveColor.clone());
        container.materials.push(material);
        mesh.material = material;
      }
      const material = mesh.material;
      if (material?.emissiveColor) {
        material.emissiveColor.set(6, 4.68, 2.7);
        for (const instance of roads.groups.get(LENS_ASSET) ?? []) {
          if (instance.metadata?.sourceId === mesh.uniqueId) instance.material = material;
        }
      }
    }
  }

  return {
    update,
    setNight(value) {
      night = value;
      lastUpdate = -Infinity;
      if (!night) for (const entry of roads.loaded.values()) {
        if (entry.resource.id !== LENS_ASSET) continue;
        for (const mesh of entry.value.meshes) {
          if (!isLens(mesh)) continue;
          const material = mesh.material;
          const original = material && originalEmission.get(material);
          if (original) material.emissiveColor.copyFrom(original);
        }
      }
    },
  };
}
