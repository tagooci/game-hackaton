import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder';
import { TransformNode } from '@babylonjs/core/Meshes/transformNode';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial';
import { DynamicTexture } from '@babylonjs/core/Materials/Textures/dynamicTexture';
import { Color3 } from '@babylonjs/core/Maths/math.color';
import type { Scene } from '@babylonjs/core/scene';
import type { PlayerState } from '../network/protocol';

/** Личный маркер финиша; физические препятствия не создаёт. */
export function createFinishArch(scene: Scene, pose: PlayerState) {
  const root = new TransformNode('personal-finish', scene);
  root.position.set(pose.x, pose.y ?? 0, pose.z);
  root.rotation.y = pose.heading;
  const material = new StandardMaterial('finish-material', scene);
  material.diffuseColor = new Color3(.15, .8, .35);
  for (const x of [-1.9, 1.9]) {
    const post = MeshBuilder.CreateBox('finish-post', { width: .15, height: 3.6, depth: .15 }, scene);
    post.parent = root; post.position.set(x, 1.8, 0); post.material = material;
  }
  const texture = new DynamicTexture('finish-label', { width: 512, height: 128 }, scene, false);
  texture.drawText('ФИНИШ', null, 92, 'bold 80px sans-serif', 'white', '#168448', true);
  const bannerMaterial = new StandardMaterial('finish-banner', scene);
  bannerMaterial.diffuseTexture = texture;
  bannerMaterial.emissiveColor = new Color3(.4, .4, .4);
  bannerMaterial.backFaceCulling = false;
  const banner = MeshBuilder.CreatePlane('finish-banner', { width: 3.95, height: .65 }, scene);
  banner.parent = root; banner.position.y = 3.4; banner.material = bannerMaterial;
  return { dispose() { root.dispose(); material.dispose(); bannerMaterial.dispose(); texture.dispose(); } };
}
