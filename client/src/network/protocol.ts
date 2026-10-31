export interface PlayerState {
  position: { x: number; y: number; z: number };
  yaw: number;
  pitch: number;
}

export interface PlayerStateMessage extends PlayerState {
  type: 'player_state';
  seq: number;
}
