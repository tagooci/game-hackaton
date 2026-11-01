import { parseServerMessage } from './protocol.ts';
import type { ScenePrepare, ServerMessage, VehicleControls } from './protocol';

interface ConnectionOptions {
  getControls: () => VehicleControls;
  takeRespawn?: () => boolean;
  prepareScene: (message: ScenePrepare) => Promise<void>;
  onMessage: (message: ServerMessage) => void;
  onDisconnect: () => void;
  onPing?: (milliseconds: number | null) => void;
  onStatus: (status: string) => void;
  onSessionEnd: (code: number) => void;
}

/** Авторизация выполнена HTTP-cookie; ввод отправляется только после scene_start. */
export function startStateSender(url: string, options: ConnectionOptions): () => void {
  let socket: WebSocket;
  let timer: ReturnType<typeof setInterval> | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let prepared: ScenePrepare | undefined;
  let active = false;
  let seq = 0;
  let inputHz = 20;
  let lastTick = -1;
  let startTick = 0;
  let pingTimer: ReturnType<typeof setInterval> | undefined;
  let pingId = 0;
  let pendingPing: { id: number; sentAt: number } | undefined;

  function sendInput(): void {
    if (!active || !prepared || lastTick < startTick || socket.readyState !== WebSocket.OPEN || socket.bufferedAmount) return;
    if (options.takeRespawn?.()) {
      socket.send(JSON.stringify({ type: 'respawn', sceneId: prepared.sceneId, epoch: prepared.epoch }));
      return;
    }
    socket.send(JSON.stringify({ type: 'input', sceneId: prepared.sceneId, epoch: prepared.epoch, seq: ++seq, ...options.getControls() }));
  }
  function connect(): void {
    if (stopped) return;
    options.onStatus('Подключение к серверу…');
    prepared = undefined;
    active = false;
    lastTick = -1;
    pendingPing = undefined;
    options.onPing?.(null);
    const connection = new WebSocket(url);
    socket = connection;
    connection.onopen = () => {
      connection.send(JSON.stringify({ type: 'join', v: 2 }));
      timeout = setTimeout(() => connection.close(), 30000);
    };
    connection.onmessage = async event => {
      if (connection !== socket || stopped || typeof event.data !== 'string') return;
      const message = parseServerMessage(event.data);
      if (!message) return;
      if (message.type === 'pong') {
        if (pendingPing?.id === message.id) {
          options.onPing?.(Math.round(performance.now() - pendingPing.sentAt));
          pendingPing = undefined;
        }
        return;
      }
      if (message.type === 'welcome') {
        inputHz = message.inputHz;
        const measurePing = () => {
          if (stopped || connection !== socket || connection.readyState !== WebSocket.OPEN) return;
          if (pendingPing) {
            if (performance.now() - pendingPing.sentAt < 5000) return;
            pendingPing = undefined;
            options.onPing?.(null);
          }
          if (connection.bufferedAmount) return;
          pendingPing = { id: ++pingId, sentAt: performance.now() };
          connection.send(JSON.stringify({ type: 'ping', id: pendingPing.id }));
        };
        clearInterval(pingTimer);
        measurePing();
        pingTimer = setInterval(measurePing, 2000);
      }
      if (message.type === 'scene_prepare') {
        if (prepared && message.epoch <= prepared.epoch) return;
        active = false;
        clearInterval(timer);
        prepared = message;
        seq = 0;
        options.onMessage(message);
        options.onStatus('Загрузка сцены…');
        try {
          await options.prepareScene(message);
          if (stopped || connection !== socket || prepared !== message || connection.readyState !== WebSocket.OPEN) return;
          connection.send(JSON.stringify({ type: 'scene_ready', sceneId: message.sceneId, epoch: message.epoch, revision: message.plan.revision }));
        } catch (error) {
          options.onStatus(`Ошибка загрузки: ${error instanceof Error ? error.message : error}`);
          stopped = true;
          connection.close();
        }
        return;
      }
      if (message.type === 'scene_start' || message.type === 'snapshot') {
        if (!prepared || message.sceneId !== prepared.sceneId || message.epoch !== prepared.epoch) return;
        if (message.type === 'scene_start') {
          clearTimeout(timeout);
          active = true;
          startTick = message.startTick;
          clearInterval(timer);
          timer = setInterval(sendInput, 1000 / inputHz);
        } else {
          if (!active || message.tick <= lastTick) return;
          lastTick = message.tick;
          if (lastTick >= startTick) options.onStatus('');
        }
      }
      if (message.type === 'error') options.onStatus(`Сервер: ${message.text}`);
      options.onMessage(message);
    };
    connection.onclose = event => {
      if (connection !== socket) return;
      active = false;
      clearInterval(timer);
      clearInterval(pingTimer);
      pendingPing = undefined;
      options.onPing?.(null);
      clearTimeout(timeout);
      options.onDisconnect();
      if (stopped) return;
      if (event.code === 1008 || event.code === 4001) {
        stopped = true;
        options.onSessionEnd(event.code);
      } else {
        options.onStatus('Связь потеряна. Переподключение…');
        retry = setTimeout(connect, 3000);
      }
    };
    connection.onerror = () => connection.close();
  }
  window.addEventListener('blur', sendInput);
  document.addEventListener('visibilitychange', sendInput);
  document.addEventListener('pointerlockchange', sendInput);
  connect();
  return () => {
    stopped = true;
    clearInterval(timer);
    clearInterval(pingTimer);
    clearTimeout(retry);
    clearTimeout(timeout);
    window.removeEventListener('blur', sendInput);
    document.removeEventListener('visibilitychange', sendInput);
    document.removeEventListener('pointerlockchange', sendInput);
    socket.onmessage = null;
    socket.onclose = null;
    socket.onopen = null;
    socket.close();
  };
}
