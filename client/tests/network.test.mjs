import assert from 'node:assert/strict';
import { test } from 'node:test';
import { startStateSender } from '../src/network/stateSender.ts';
import { parseServerMessage } from '../src/network/protocol.ts';

const welcome = { type: 'welcome', v: 2, playerId: 'p1', inputHz: 20 };
const scene = { sceneId: 'world:main', epoch: 1 };
const prepare = { type: 'scene_prepare', ...scene, spawn: {x: 0, z: 0, heading: 0}, plan: {mapManifestUrl: '/content/world/manifest.json', revision: 1, resources: []} };
const start = { type: 'scene_start', ...scene, tick: 2, startTick: 3 };
const snapshot = { type: 'snapshot', ...scene, tick: 3, players: [] };

function setup(t, callbacks = {}) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  globalThis.window = new EventTarget();
  globalThis.document = new EventTarget();
  const sockets = [];
  class Socket {
    static OPEN = 1;
    readyState = 0; bufferedAmount = 0; sent = [];
    constructor() { sockets.push(this); }
    send(data) { assert.equal(this.readyState, 1); this.sent.push(JSON.parse(data)); }
    open() { this.readyState = 1; this.onopen?.(); }
    message(data) { return this.onmessage?.({ data: JSON.stringify(data) }); }
    close(code = 1000) { this.readyState = 3; this.onclose?.({ code }); }
  }
  t.mock.property(globalThis, 'WebSocket', Socket);
  const received = [];
  const ended = [];
  const stop = startStateSender('ws://localhost/ws/v2', {
    getControls: () => ({throttle: 1, steering: -1, brake: 0}),
    prepareScene: async () => {}, onMessage: m => received.push(m),
    onDisconnect() {}, onStatus() {}, onSessionEnd: code => ended.push(code), ...callbacks,
  });
  t.after(() => { stop(); delete globalThis.window; delete globalThis.document; });
  return { sockets, stop, received, ended };
}

async function activate(ws) {
  ws.open(); await ws.message(welcome); await ws.message(prepare); await ws.message(start); await ws.message(snapshot);
}

test('v2 input waits for resources, scene_start and startTick; slow connections never queue', async t => {
  let resolve;
  const {sockets} = setup(t, {prepareScene: () => new Promise(r => { resolve = r; })});
  const ws = sockets[0]; ws.open(); await ws.message(welcome);
  const loading = ws.message(prepare);
  t.mock.timers.tick(100);
  assert.deepEqual(ws.sent, [{type: 'join', v: 2}]);
  resolve(); await loading;
  assert.equal(ws.sent[1].type, 'scene_ready');
  await ws.message(start); t.mock.timers.tick(50);
  assert.equal(ws.sent.length, 2);
  await ws.message(snapshot); t.mock.timers.tick(50);
  assert.deepEqual(ws.sent[2], {type: 'input', ...scene, seq: 1, throttle: 1, steering: -1, brake: 0});
  ws.bufferedAmount = 10; t.mock.timers.tick(100); assert.equal(ws.sent.length, 3);
});

test('reconnect resets handshake and seq; session close codes do not reconnect', async t => {
  const { sockets, ended } = setup(t); await activate(sockets[0]); t.mock.timers.tick(50);
  sockets[0].close(); t.mock.timers.tick(3000); assert.equal(sockets.length, 2);
  await activate(sockets[1]); t.mock.timers.tick(50); assert.equal(sockets[1].sent.at(-1).seq, 1);
  sockets[1].close(4001); t.mock.timers.tick(6000); assert.deepEqual(ended, [4001]); assert.equal(sockets.length, 2);
});

test('stale snapshots and stale load completions cannot activate a new scene', async t => {
  const {sockets, received} = setup(t); const ws = sockets[0]; await activate(ws);
  await ws.message({...snapshot, epoch: 0, tick: 100});
  await ws.message({...snapshot, tick: 1});
  assert.equal(received.filter(m => m.type === 'snapshot').length, 1);
  await ws.message({...prepare, epoch: 2}); t.mock.timers.tick(100);
  assert.equal(ws.sent.at(-1).type, 'scene_ready');
});

test('lost focus immediately sends braking input and invalid messages are ignored', async t => {
  let brake = 0;
  const {sockets} = setup(t, {getControls: () => ({throttle: 0, steering: 0, brake})});
  await activate(sockets[0]); brake = 1; window.dispatchEvent(new Event('blur'));
  assert.equal(sockets[0].sent.at(-1).brake, 1);
  for (const text of ['invalid', 'null', '{"type":"welcome"}', '{"type":"snapshot","players":[null]}']) assert.equal(parseServerMessage(text), undefined);
});
