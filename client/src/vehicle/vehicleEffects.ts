import '@babylonjs/core/Engines/Extensions/engine.dynamicTexture';
import { Mesh } from '@babylonjs/core/Meshes/mesh';
import { ParticleSystem } from '@babylonjs/core/Particles/particleSystem';
import { DynamicTexture } from '@babylonjs/core/Materials/Textures/dynamicTexture';
import { TransformNode } from '@babylonjs/core/Meshes/transformNode';
import { Vector3 } from '@babylonjs/core/Maths/math.vector';
import { Color4 } from '@babylonjs/core/Maths/math.color';
import type { Scene } from '@babylonjs/core/scene';

const textures = new WeakMap<Scene, DynamicTexture>();
function smokeTexture(scene: Scene) {
  let texture = textures.get(scene);
  if (!texture) {
    texture = new DynamicTexture('smoke', 64, scene, false);
    const ctx = texture.getContext();
    const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, 'rgba(255,255,255,.85)');
    gradient.addColorStop(.5, 'rgba(255,255,255,.5)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 64, 64); texture.update();
    textures.set(scene, texture);
    const shared = texture;
    scene.onDisposeObservable.addOnce(() => shared.dispose());
  }
  return texture;
}

/** Только визуальные эффекты; физика и положение коллайдера не меняются. */
export function createVehicleEffects(scene: Scene, root: TransformNode, length: number) {
  const visual = new TransformNode(`${root.name}-effects`, scene);
  visual.parent = root;
  let throttle = 0, grounded = true, power = 0;
  const systems = [-1, 1].map(side => {
    const emitter = new Mesh(`${root.name}-rear-${side}`, scene);
    emitter.parent = root;
    emitter.position.set(side * length * .22, .12, -length * .32);
    const smoke = new ParticleSystem(`${root.name}-smoke-${side}`, 128, scene);
    smoke.particleTexture = smokeTexture(scene);
    smoke.emitter = emitter;
    smoke.minEmitBox = new Vector3(-.08, 0, -.08);
    smoke.maxEmitBox = new Vector3(.08, .02, .08);
    smoke.direction1 = new Vector3(-.2, .3, -.4);
    smoke.direction2 = new Vector3(.2, .6, .2);
    smoke.color1 = new Color4(.75, .75, .72, .6);
    smoke.color2 = new Color4(.9, .9, .85, .5);
    smoke.colorDead = new Color4(.85, .85, .8, 0);
    smoke.minSize = .45; smoke.maxSize = 1.25;
    smoke.addSizeGradient(0, .45); smoke.addSizeGradient(1, 1.25);
    smoke.minLifeTime = .7; smoke.maxLifeTime = 1.1;
    smoke.minEmitPower = .4; smoke.maxEmitPower = .8;
    smoke.gravity = new Vector3(0, .3, 0);
    smoke.blendMode = ParticleSystem.BLENDMODE_STANDARD;
    smoke.emitRate = 0; smoke.start();
    return { smoke, emitter };
  });
  const observer = scene.onBeforeRenderObservable.add(() => {
    const dt = Math.min(scene.getEngine().getDeltaTime() / 1000, .1);
    const target = grounded ? Math.abs(throttle) : 0;
    power += (target - power) * (1 - Math.exp(-9 * dt));
    visual.rotation.x = -.055 * power;
    visual.scaling.set(1 + .015 * power, 1 - .045 * power, 1 + .025 * power);
    visual.position.y = .035 * power;
    for (const { smoke } of systems) smoke.emitRate = target * 90;
  });
  return {
    visual,
    setMotion(gas: number, onGround: boolean) { throttle = gas; grounded = onGround; },
    dispose() {
      scene.onBeforeRenderObservable.remove(observer);
      for (const { smoke, emitter } of systems) { smoke.dispose(false); emitter.dispose(); }
      visual.dispose();
    },
  };
}
