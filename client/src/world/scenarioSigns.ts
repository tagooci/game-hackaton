import { TransformNode } from '@babylonjs/core/Meshes/transformNode';
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial';
import { DynamicTexture } from '@babylonjs/core/Materials/Textures/dynamicTexture';
import { Color3 } from '@babylonjs/core/Maths/math.color';
import type { Scene } from '@babylonjs/core/scene';

/** Blue roundabout signs complement the imported yield signs. */
export function createRoundaboutSigns(scene: Scene, signs: { x: number; z: number; heading: number }[]) {
  const root = new TransformNode('roundabout-signs', scene);
  const texture = new DynamicTexture('roundabout-symbol', 256, scene, false);
  const ctx = texture.getContext();
  ctx.clearRect(0, 0, 256, 256);
  ctx.fillStyle = '#1676c8'; ctx.beginPath(); ctx.arc(128, 128, 119, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 6; ctx.beginPath(); ctx.arc(128, 128, 116, 0, Math.PI * 2); ctx.stroke();
  // Three counterclockwise arrows (canvas Y increases downwards).
  ctx.lineWidth = 15; ctx.fillStyle = '#fff';
  for (let i = 0; i < 3; i++) {
    const start = i * Math.PI * 2 / 3;
    const end = start - 1.35;
    ctx.beginPath(); ctx.arc(128, 128, 63, start, end, true); ctx.stroke();
    const x = 128 + 63 * Math.cos(end), y = 128 + 63 * Math.sin(end);
    const dx = Math.sin(end), dy = -Math.cos(end);
    ctx.beginPath(); ctx.moveTo(x + dx * 16, y + dy * 16);
    ctx.lineTo(x - dx * 12 - dy * 17, y - dy * 12 + dx * 17);
    ctx.lineTo(x - dx * 12 + dy * 17, y - dy * 12 - dx * 17); ctx.closePath(); ctx.fill();
  }
  texture.hasAlpha = true; texture.update();
  const material = new StandardMaterial('roundabout-sign-face', scene);
  material.diffuseTexture = texture; material.useAlphaFromDiffuseTexture = true;
  material.emissiveColor = new Color3(.35, .35, .35); material.backFaceCulling = false;
  for (const [index, sign] of signs.entries()) {
    const board = MeshBuilder.CreatePlane(`roundabout-sign-${index}`, { size: .75 }, scene);
    board.parent = root; board.position.set(sign.x, 1.8, sign.z); board.rotation.y = sign.heading; board.material = material;
  }
  return { dispose() { root.dispose(); material.dispose(); texture.dispose(); } };
}
