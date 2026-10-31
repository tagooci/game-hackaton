import { Scene } from '@babylonjs/core/scene.js';
import { Color3, Color4 } from '@babylonjs/core/Maths/math.color.js';
import { Vector3 } from '@babylonjs/core/Maths/math.vector.js';
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder.js';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial.js';
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight.js';
import type { Engine } from '@babylonjs/core/Engines/engine';
import type { JunctionDefinition, Role } from './definition';

/** Every visual dimension comes from the same map definition Python reads. */
export function createJunctionScene(engine: Engine, definition: JunctionDefinition) {
  const scene = new Scene(engine);
  scene.clearColor = new Color4(.66, .8, .9, 1);
  new HemisphericLight('junction-daylight', new Vector3(.3, 1, .2), scene);
  function material(name: string, hex: string) {
    const result = new StandardMaterial(name, scene);
    result.diffuseColor = Color3.FromHexString(hex);
    result.specularColor = Color3.Black();
    return result;
  }
  const grass = material('grass', '#83a976');
  const asphalt = material('asphalt', '#414953');
  const white = material('markings', '#f6f1da');
  const steel = material('rails', '#b8bfca');
  const curb = material('curbs', '#b5b8b0');
  function box(name: string, x: number, y: number, z: number,
               width: number, height: number, depth: number, mat: StandardMaterial) {
    const mesh = MeshBuilder.CreateBox(name, { width, height, depth }, scene);
    mesh.position.set(x, y, z);
    mesh.material = mat;
    return mesh;
  }
  box('ground', 0, -.2, 0, definition.worldSize, .3, definition.worldSize, grass);
  const width = definition.roadWidth;
  const size = definition.worldSize;
  box('north-south-road', 0, -.035, 0, width, .05, size, asphalt);
  box('east-west-road', 0, -.03, 0, size, .05, width, asphalt);
  for (let distance = -size / 2 + 2; distance < size / 2; distance += 4) {
    if (Math.abs(distance) < width / 2 + 2) continue;
    box(`lane-ns-${distance}`, 0, .005, distance, .12, .02, 2, white);
    box(`lane-ew-${distance}`, distance, .005, 0, 2, .02, .12, white);
  }
  for (const [index, line] of definition.stopLines.entries()) {
    const mesh = box(`stop-line-${index}`, line.x, .015, line.z, line.width, .025, .25, white);
    mesh.rotation.y = line.heading;
  }
  // One straight tram track: it belongs to the third player's route.
  const tram = definition.roles.find(role => role.vehicleType === 'tram')!;
  for (const offset of [-.72, .72]) {
    box(`rail-${offset}`, tram.spawn.x + offset, .025, 0, .08, .035, size, steel);
  }
  for (const x of [-1, 1]) for (const z of [-1, 1]) {
    box(`sidewalk-${x}-${z}`, x * (width / 2 + 10), .08, z * (width / 2 + 10), 18, .22, 18, curb);
    const trunk = material(`trunk-${x}-${z}`, '#765941');
    const leaves = material(`leaves-${x}-${z}`, '#468064');
    box('tree-trunk', x * 18, 1, z * 18, .6, 2, .6, trunk);
    const tree = MeshBuilder.CreateCylinder('tree-crown', { diameterTop: 0, diameterBottom: 5, height: 6, tessellation: 5 }, scene);
    tree.position.set(x * 18, 4.5, z * 18);
    tree.material = leaves;
  }
  return scene;
}

/** Ground-centred model root. Replace its children with GLB, retaining the pivot. */
export function createVehicle(scene: Scene, role: Role, name: string) {
  const root = MeshBuilder.CreateBox(name, { size: .01 }, scene);
  root.isVisible = false;
  const bodyMat = new StandardMaterial(`${name}-paint`, scene);
  bodyMat.diffuseColor = Color3.FromHexString(
    role.vehicleType === 'truck' ? '#de943d' : role.vehicleType === 'tram' ? '#be4945' : '#3987ae');
  const glass = new StandardMaterial(`${name}-glass`, scene);
  glass.diffuseColor = Color3.FromHexString('#263b4c');
  const tyre = new StandardMaterial(`${name}-tyres`, scene);
  tyre.diffuseColor = Color3.FromHexString('#202329');
  function part(label: string, width: number, height: number, depth: number,
                x: number, y: number, z: number, mat: StandardMaterial) {
    const mesh = MeshBuilder.CreateBox(`${name}-${label}`, { width, height, depth }, scene);
    mesh.parent = root;
    mesh.position.set(x, y, z);
    mesh.material = mat;
  }
  part('body', role.width, role.height * .55, role.length, 0, role.height * .36, 0, bodyMat);
  const cabLength = role.vehicleType === 'truck' ? 2 : role.length * .55;
  const cabZ = role.vehicleType === 'truck' ? role.length / 2 - 1.1 : 0;
  part('windows', role.width * .86, role.height * .35, cabLength, 0, role.height * .8, cabZ, glass);
  part('roof', role.width * .92, .12, cabLength, 0, role.height, cabZ, bodyMat);
  for (const x of [-1, 1]) for (const z of [-1, 1]) {
    part('wheel', .22, .65, .75, x * role.width / 2, .33, z * role.length * .32, tyre);
  }
  root.position.set(role.spawn.x, 0, role.spawn.z);
  root.rotation.y = role.spawn.heading;
  return root;
}
