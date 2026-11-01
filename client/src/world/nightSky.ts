import { Color3 } from '@babylonjs/core/Maths/math.color';
import { Vector3 } from '@babylonjs/core/Maths/math.vector';
import { Mesh } from '@babylonjs/core/Meshes/mesh';
import { VertexData } from '@babylonjs/core/Meshes/mesh.vertexData';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial';
import type { Scene } from '@babylonjs/core/scene';

export function createNightSky(scene: Scene) {
  // Camera-centred celestial hemisphere: translation has no parallax,
  // while rotation changes which stars are visible. Fits within camera.maxZ.
  const sky = new Mesh('night-sky-stars', scene);
  sky.infiniteDistance = true;
  sky.isPickable = false;
  sky.alwaysSelectAsActiveMesh = true;
  sky.applyFog = false;
  const positions: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i < 420; i++) {
    const height = 0.035 + 0.96 * (i + 0.5) / 420;
    const azimuth = i * 2.399963229728653;
    const horizontal = Math.sqrt(1 - height * height);
    const direction = new Vector3(Math.cos(azimuth) * horizontal, height, Math.sin(azimuth) * horizontal);
    const center = direction.scale(110);
    const right = Vector3.Cross(direction, Vector3.Up()).normalize();
    const up = Vector3.Cross(right, direction).normalize();
    const size = 0.08 + (i % 7) * 0.025;
    const base = positions.length / 3;
    positions.push(center.x, center.y, center.z);
    for (let point = 0; point < 10; point++) {
      const angle = point * Math.PI / 5;
      const radius = point % 2 ? size * 0.4 : size;
      const vertex = center.add(right.scale(Math.sin(angle) * radius)).add(up.scale(Math.cos(angle) * radius));
      positions.push(vertex.x, vertex.y, vertex.z);
      indices.push(base, base + 1 + point, base + 1 + (point + 1) % 10);
    }
  }
  const data = new VertexData();
  data.positions = positions;
  data.indices = indices;
  data.applyToMesh(sky);
  const material = new StandardMaterial('night-sky-stars', scene);
  material.disableLighting = true;
  material.emissiveColor = new Color3(1, 0.85, 0.38);
  material.backFaceCulling = false;
  material.disableDepthWrite = true;
  material.fogEnabled = false;
  sky.material = material;
  sky.setEnabled(false);
  return {
    setNight(value: boolean) { sky.setEnabled(value); },
    dispose() { sky.dispose(); material.dispose(); },
  };
}
