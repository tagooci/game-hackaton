export interface PlayerState {
  x: number;
  z: number;
  heading: number;
}

export interface PlayerStateMessage extends PlayerState {
  type: 'state';
}

export interface PlayerSnapshot extends PlayerState {
  id: string;
}

export interface PlayerInfo extends PlayerSnapshot {
  name: string;
  zone: string;
}

export interface WelcomeMessage extends PlayerState {
  type: 'welcome';
  id: string;
  zone: string;
  players: PlayerInfo[];
}

export type ServerMessage =
  | WelcomeMessage
  | { type: 'snapshot'; tick: number; players: PlayerSnapshot[] }
  | ({ type: 'player_joined' } & PlayerInfo)
  | { type: 'player_left'; id: string }
  | { type: 'error'; code: string; text: string };

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isState(value: Record<string, unknown>): boolean {
  return ['x', 'z', 'heading'].every(key => typeof value[key] === 'number' && Number.isFinite(value[key]));
}

function isPlayer(value: unknown): boolean {
  return isObject(value) && typeof value.id === 'string' && isState(value);
}

function isPlayerInfo(value: unknown): boolean {
  return isPlayer(value) && isObject(value) && typeof value.name === 'string' && typeof value.zone === 'string';
}

/** Ignore unknown types and extra fields, as required by protocol v1. */
export function parseServerMessage(text: string): ServerMessage | undefined {
  let value: unknown;
  try { value = JSON.parse(text); } catch { return undefined; }
  if (!isObject(value)) return undefined;
  switch (value.type) {
    case 'welcome':
      if (!isPlayer(value) || typeof value.zone !== 'string' || !Array.isArray(value.players) || !value.players.every(isPlayerInfo)) return undefined;
      break;
    case 'snapshot':
      if (!Number.isSafeInteger(value.tick) || !Array.isArray(value.players) || !value.players.every(isPlayer)) return undefined;
      break;
    case 'player_joined':
      if (!isPlayerInfo(value)) return undefined;
      break;
    case 'player_left':
      if (typeof value.id !== 'string') return undefined;
      break;
    case 'error':
      if (typeof value.code !== 'string' || typeof value.text !== 'string') return undefined;
      break;
    default:
      return undefined;
  }
  return value as unknown as ServerMessage;
}
