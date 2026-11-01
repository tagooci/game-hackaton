import { Mesh } from '@babylonjs/core';

// Создаём независимые CPU-буферы до впекания зеркального преобразования glTF.
// bakeTransformIntoVertices меняет позиции, нормали и порядок индексов на месте.
export function createRoadMesh(source, scene, transform, name) {
  const mesh = new Mesh(name, scene);
  for (const kind of source.getVerticesDataKinds()) {
    const buffer = source.getVertexBuffer(kind);
    mesh.setVerticesData(kind, buffer.getFloatData(source.getTotalVertices(), true));
  }
  mesh.setIndices(source.getIndices().slice());
  mesh.material = source.material;
  // glTF задаёт своё направление лицевой стороны. Оно принадлежит Mesh,
  // поэтому одного копирования материала недостаточно.
  mesh.sideOrientation = source.sideOrientation;
  mesh.bakeTransformIntoVertices(transform);
  return mesh;
}
