export interface PlayerState {
  x: number;
  z: number;
  heading: number;
}

export interface PlayerStateMessage extends PlayerState {
  type: 'state';
}
