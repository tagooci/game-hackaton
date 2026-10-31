export type VehicleType = 'car' | 'truck' | 'tram';
export interface Pose { x: number; z: number; heading: number }
export interface Role {
  roleId: string; vehicleType: VehicleType; entry: string; spawn: Pose;
  length: number; width: number; height: number;
}
export interface JunctionDefinition {
  schemaVersion: number; scenarioId: string; mapId: string; title: string;
  worldSize: number; roadWidth: number; intersectionHalfSize: number; finishDistance: number;
  roles: Role[];
  stopLines: (Pose & { width: number })[];
}

export async function loadJunction(signal: AbortSignal): Promise<JunctionDefinition> {
  const response = await fetch('/scenarios/priority-01.json', { signal, cache: 'no-store' });
  if (!response.ok) throw new Error(`Map download failed: ${response.status}`);
  const data = await response.json();
  if (data.schemaVersion !== 1 || data.mapId !== 'junction-01' || !Array.isArray(data.roles)) {
    throw new Error('Unsupported junction definition');
  }
  return data;
}
