import type { PlayerState, PlayerStateMessage } from './protocol';

const SEND_INTERVAL_MS = 1000 / 15;
const RECONNECT_DELAY_MS = 3000;

/** Sends the latest state only; disconnected/slow connections never accumulate a queue. */
export function startStateSender(url: string, getState: () => PlayerState): () => void {
  let socket: WebSocket | undefined;
  let sendTimer: ReturnType<typeof setInterval> | undefined;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;

  function sendState(): void {
    if (socket?.readyState !== WebSocket.OPEN || socket.bufferedAmount > 0) return;
    const message: PlayerStateMessage = {
      type: 'state',
      ...getState(),
    };
    socket.send(JSON.stringify(message));
  }

  function connect(): void {
    if (stopped) return;
    socket = new WebSocket(url);
    socket.onopen = () => {
      console.info('Соединение с сервером установлено:', url);
      sendState();
      sendTimer = setInterval(sendState, SEND_INTERVAL_MS);
    };
    socket.onclose = () => {
      clearInterval(sendTimer);
      if (!stopped) reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
    };
    // The browser logs connection errors; reconnection is handled by onclose.
    socket.onerror = () => socket?.close();
  }

  connect();

  return () => {
    stopped = true;
    clearInterval(sendTimer);
    clearTimeout(reconnectTimer);
    if (socket) {
      socket.onopen = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    }
  };
}
