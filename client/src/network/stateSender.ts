import { parseServerMessage } from './protocol.ts';
import type { PlayerState, PlayerStateMessage, ServerMessage, WelcomeMessage } from './protocol';

const SEND_INTERVAL_MS = 1000 / 20;
const RECONNECT_DELAY_MS = 3000;
const JOIN_TIMEOUT_MS = 5000;

interface ConnectionOptions {
  name: string;
  getState: () => PlayerState;
  onWelcome: (message: WelcomeMessage) => void;
  onMessage?: (message: ServerMessage) => void;
  onDisconnect?: () => void;
}

/** Sends the latest state only; disconnected/slow connections never accumulate a queue. */
export function startStateSender(url: string, options: ConnectionOptions): () => void {
  let socket: WebSocket | undefined;
  let sendTimer: ReturnType<typeof setInterval> | undefined;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let joinTimer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let joined = false;

  function sendState(): void {
    if (!joined || socket?.readyState !== WebSocket.OPEN || socket.bufferedAmount > 0) return;
    const state = options.getState();
    if (![state.x, state.z, state.heading].every(Number.isFinite)) return;
    const message: PlayerStateMessage = {
      type: 'state',
      x: Number(state.x.toFixed(2)),
      z: Number(state.z.toFixed(2)),
      heading: Number(state.heading.toFixed(2)),
    };
    socket.send(JSON.stringify(message));
  }

  function connect(): void {
    if (stopped) return;
    joined = false;
    const connection = new WebSocket(url);
    socket = connection;
    connection.onopen = () => {
      connection.send(JSON.stringify({ type: 'join', name: options.name, v: 1 }));
      // A silent/wrong endpoint must not leave the client waiting forever.
      joinTimer = setTimeout(() => connection.close(), JOIN_TIMEOUT_MS);
    };
    connection.onmessage = event => {
      if (typeof event.data !== 'string') return;
      const message = parseServerMessage(event.data);
      if (!message) return;
      if (!joined && message.type !== 'welcome' && message.type !== 'error') return;
      if (message.type === 'error') {
        console.warn(`Сервер: ${message.code}: ${message.text}`);
      } else if (message.type === 'welcome' && !joined) {
        clearTimeout(joinTimer);
        options.onWelcome(message);
        joined = true;
        console.info(`Вход выполнен: ${message.id}`, url);
        sendState();
        sendTimer = setInterval(sendState, SEND_INTERVAL_MS);
      }
      options.onMessage?.(message);
    };
    connection.onclose = () => {
      joined = false;
      clearInterval(sendTimer);
      clearTimeout(joinTimer);
      options.onDisconnect?.();
      if (!stopped) reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
    };
    // The browser logs connection errors; reconnection is handled by onclose.
    connection.onerror = () => connection.close();
  }

  connect();

  return () => {
    stopped = true;
    joined = false;
    clearInterval(sendTimer);
    clearTimeout(reconnectTimer);
    clearTimeout(joinTimer);
    if (socket) {
      socket.onopen = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.onmessage = null;
      socket.close();
    }
  };
}
