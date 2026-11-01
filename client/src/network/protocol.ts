export interface PlayerState { x: number; z: number; heading: number; y?: number; pitch?: number }
export interface VehicleControls { throttle: number; steering: number; brake: number }
export interface PlayerSnapshot extends PlayerState {
  id: string; name: string; vehicleType: string; speed: number; steering: number; lastInputSeq: number; wheelAngle: number; color: number; throttle?: number; grounded?: boolean;
}
export interface SceneContext { sceneId: string; epoch: number }
export interface ScenePrepare extends SceneContext {
  type: 'scene_prepare'; spawn: PlayerState; finish?: PlayerState | null;
  sceneKind: 'world' | 'scenario'; scenarioId: string | null; roleId: string | null;
  weather: 'clear' | 'rain' | 'fog';
  plan: { mapManifestUrl: string; revision: number; resources: { id: string; url: string; bytes: number }[] };
}
export type ServerMessage =
  | { type: 'welcome'; v: 2; playerId: string; inputHz: number }
  | ScenePrepare
  | ({ type: 'scene_start'; startTick: number; tick: number } & SceneContext)
  | ({ type: 'snapshot'; tick: number; players: PlayerSnapshot[]; scenarioResult?: string | null; scenarioQueue?: { count: number; x: number; y: number; z: number } | null } & SceneContext)
  | { type: 'agent_feedback'; resultId: string; sessionId: string; playerId: string; feedback: { successful: { category: string; comment: string }[]; errors: { violationId: string; comment: string }[]; experience: string } }
  | { type: 'agent_feedback_error'; resultId: string; sessionId: string; text: string }
  | { type: 'error'; code: string; text: string };

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function pose(value: unknown): boolean {
  return object(value) && ['x', 'z', 'heading'].every(key => typeof value[key] === 'number' && Number.isFinite(value[key]))
    && ['y', 'pitch'].every(key => value[key] === undefined || typeof value[key] === 'number' && Number.isFinite(value[key]));
}
function context(value: Record<string, unknown>): boolean {
  return typeof value.sceneId === 'string' && Number.isSafeInteger(value.epoch);
}
export function parseServerMessage(text: string): ServerMessage | undefined {
  let v: unknown;
  try { v = JSON.parse(text); } catch { return; }
  if (!object(v)) return;
  switch (v.type) {
    case 'welcome':
      if (v.v !== 2 || typeof v.playerId !== 'string' || !Number.isInteger(v.inputHz) || Number(v.inputHz) < 1 || Number(v.inputHz) > 60) return;
      break;
    case 'scene_prepare':
      if (!context(v) || !pose(v.spawn) || !['clear', 'rain', 'fog'].includes(v.weather as string) || !object(v.plan) || typeof v.plan.mapManifestUrl !== 'string' || !Number.isSafeInteger(v.plan.revision) || !Array.isArray(v.plan.resources)
        || !v.plan.resources.every(r => object(r) && typeof r.id === 'string' && typeof r.url === 'string' && Number.isSafeInteger(r.bytes) && Number(r.bytes) >= 0)) return;
      break;
    case 'scene_start':
      if (!context(v) || !Number.isSafeInteger(v.startTick) || !Number.isSafeInteger(v.tick)) return;
      break;
    case 'snapshot':
      if (!context(v) || !Number.isSafeInteger(v.tick) || !Array.isArray(v.players)
        || !v.players.every(p => object(p) && typeof p.id === 'string' && typeof p.name === 'string' && pose(p)
          && typeof p.wheelAngle === 'number' && Number.isFinite(p.wheelAngle) && Number.isInteger(p.color) && Number(p.color) >= 0 && Number(p.color) < 5)) return;
      break;
    case 'agent_feedback':
      if (typeof v.resultId !== 'string' || typeof v.sessionId !== 'string' || typeof v.playerId !== 'string' || !object(v.feedback) || !Array.isArray(v.feedback.successful) || !Array.isArray(v.feedback.errors) || typeof v.feedback.experience !== 'string') return;
      break;
    case 'agent_feedback_error':
      if (typeof v.resultId !== 'string' || typeof v.sessionId !== 'string' || typeof v.text !== 'string') return;
      break;
    case 'error':
      if (typeof v.code !== 'string' || typeof v.text !== 'string') return;
      break;
    default: return;
  }
  return v as unknown as ServerMessage;
}
