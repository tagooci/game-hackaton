import assert from 'node:assert/strict';
import { test } from 'node:test';
import { startStateSender } from '../src/network/stateSender.ts';
import { parseServerMessage } from '../src/network/protocol.ts';

const welcome = { type: 'welcome', id: 'p1', zone: 'world', x: 0, z: 0, heading: 0, players: [] };

function setup(t, callbacks = {}) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  const sockets = [];
  class Socket {
    static OPEN = 1;
    readyState = 0;
    bufferedAmount = 0;
    sent = [];
    constructor() { sockets.push(this); }
    send(data) { assert.equal(this.readyState, 1); this.sent.push(JSON.parse(data)); }
    open() { this.readyState = 1; this.onopen?.(); }
    message(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
    close() { this.readyState = 3; this.onclose?.(); }
  }
  t.mock.property(globalThis, 'WebSocket', Socket);
  let state = { x: 5, z: -4, heading: 1.234 };
  const stop = startStateSender('ws://localhost:8000/ws', {
    name: 'Alice',
    getState: () => state,
    onWelcome: message => { state = { x: message.x, z: message.z, heading: message.heading }; },
    ...callbacks,
  });
  t.after(stop);
  return { sockets, stop, setState: value => { state = value; } };
}

test('join precedes state; welcome spawn is applied before sending; state is rounded at 20 Hz', t => {
  const { sockets, setState } = setup(t);
  const ws = sockets[0];
  ws.open();
  assert.deepEqual(ws.sent, [{ type: 'join', name: 'Alice', v: 1 }]);
  t.mock.timers.tick(100);
  assert.equal(ws.sent.length, 1);
  ws.message(welcome);
  assert.deepEqual(ws.sent[1], { type: 'state', x: 0, z: 0, heading: 0 });
  setState({ x: 1.256, z: -3.4, heading: 1.57 });
  t.mock.timers.tick(50);
  assert.deepEqual(ws.sent[2], { type: 'state', x: 1.26, z: -3.4, heading: 1.57 });
  ws.bufferedAmount = 10;
  t.mock.timers.tick(100);
  assert.equal(ws.sent.length, 3);
});

test('reconnect requires a new welcome and disposal cancels retry', t => {
  const { sockets, stop } = setup(t);
  sockets[0].open();
  sockets[0].message(welcome);
  sockets[0].close();
  t.mock.timers.tick(3000);
  assert.equal(sockets.length, 2);
  sockets[1].open();
  assert.deepEqual(sockets[1].sent, [{ type: 'join', name: 'Alice', v: 1 }]);
  sockets[1].close();
  stop();
  t.mock.timers.tick(6000);
  assert.equal(sockets.length, 2);
});

test('silent server times out and reconnects', t => {
  const { sockets } = setup(t);
  sockets[0].open();
  t.mock.timers.tick(5000);
  assert.equal(sockets[0].readyState, 3);
  t.mock.timers.tick(3000);
  assert.equal(sockets.length, 2);
});

test('vehicle mode sends input only after server confirmation and resets sequence on reconnect', t => {
  const { sockets } = setup(t, { getControls: () => ({ throttle: 1, steering: -1, brake: 0 }) });
  sockets[0].open();
  assert.equal(sockets[0].sent[0].controlMode, 'vehicle');
  const vehicleWelcome = { ...welcome, controlMode: 'vehicle', sceneId: 'world:main', epoch: 1 };
  sockets[0].message(vehicleWelcome);
  assert.deepEqual(sockets[0].sent[1], { type: 'input', sceneId: 'world:main', epoch: 1, seq: 1, throttle: 1, steering: -1, brake: 0 });
  t.mock.timers.tick(50);
  assert.equal(sockets[0].sent[2].seq, 2);
  sockets[0].close();
  t.mock.timers.tick(3000);
  sockets[1].open();
  sockets[1].message(vehicleWelcome);
  assert.equal(sockets[1].sent[1].seq, 1);
});

test('vehicle client does not send controls to a legacy server without confirmation', t => {
  const { sockets } = setup(t, { getControls: () => ({ throttle: 1, steering: 0, brake: 0 }) });
  sockets[0].open();
  sockets[0].message(welcome);
  t.mock.timers.tick(100);
  assert.equal(sockets[0].sent.length, 1);
});

test('server events are delivered; malformed or future messages are ignored', t => {
  const received = [];
  const { sockets } = setup(t, { onMessage: message => received.push(message) });
  sockets[0].open();
  sockets[0].message({ type: 'snapshot', tick: 0, players: [] });
  assert.deepEqual(received, []);
  sockets[0].message(welcome);
  const snapshot = { type: 'snapshot', tick: 1, players: [{ id: 'p1', x: 1, z: 2, heading: 0 }] };
  sockets[0].message(snapshot);
  sockets[0].message({ type: 'future' });
  sockets[0].message({ type: 'snapshot', tick: 2, players: [null] });
  assert.deepEqual(received, [welcome, snapshot]);
  assert.equal(parseServerMessage('invalid JSON'), undefined);
  assert.equal(parseServerMessage('null'), undefined);
  assert.equal(parseServerMessage('{"type":"welcome"}'), undefined);
});
