"""Run: python -m uvicorn server.scenarios.lan:app --host 0.0.0.0 --port 8011

Standalone LAN lab, unauthenticated and limited to three connections. Not /ws/v2.
"""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
from pathlib import Path
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from .lan_room import LanRoom
from .results import ResultStore

ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(app):
    store = ResultStore(os.environ.get('SCENARIO_LAB_DB', str(ROOT / 'scenario-lab.sqlite3')))
    app.state.room = LanRoom(store)

    async def simulate():
        step_time = 1 / 30
        previous = time.monotonic()
        accumulated = 0.0
        while True:
            now = time.monotonic()
            accumulated += min(now - previous, .2)
            previous = now
            while accumulated >= step_time:
                app.state.room.advance(now - accumulated + step_time)
                accumulated -= step_time
            await asyncio.sleep(.005)

    task = asyncio.create_task(simulate())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        store.close()


app = FastAPI(lifespan=lifespan)


@app.get('/lab/health')
async def health():
    return {'status': 'ok', 'mode': 'scenario-lan-lab'}


@app.websocket('/lab/ws')
async def socket(ws: WebSocket):
    await ws.accept()
    room = app.state.room
    pid = None
    sender = None
    try:
        raw = await asyncio.wait_for(ws.receive_text(), 5)
        if len(raw.encode('utf-8')) > 16384:
            await ws.close(1009)
            return
        hello = json.loads(raw)
        if not isinstance(hello, dict) or hello.get('type') != 'lab_join' or not isinstance(hello.get('name'), str):
            await ws.close(1008)
            return
        pid = room.connect(hello['name'])
        if pid is None:
            await ws.send_json({'type': 'lab_error', 'text': 'В комнате уже три игрока. Попробуйте позже.'})
            await ws.close(1008)
            return
        await ws.send_json({'type': 'lab_welcome', 'playerId': pid})

        async def send_snapshots():
            try:
                while True:
                    await asyncio.wait_for(ws.send_json(room.snapshot(pid, time.monotonic())), 2)
                    await asyncio.sleep(.05)
            except (Exception, asyncio.CancelledError):
                # Wake the receiver if a peer stops reading snapshots.
                with suppress(Exception):
                    await ws.close()
                raise

        sender = asyncio.create_task(send_snapshots())
        rate_started = time.monotonic()
        count = 0
        while True:
            raw = await ws.receive_text()
            now = time.monotonic()
            if len(raw.encode('utf-8')) > 16384:
                await ws.close(1009)
                break
            if now - rate_started >= 1:
                count = 0
                rate_started = now
            count += 1
            if count > 60:
                await ws.close(1008)
                break
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            kind = message.get('type')
            if kind == 'lab_queue':
                room.join_queue(pid, now)
            elif kind == 'lab_leave_queue':
                room.queue.leave(pid)
            elif kind == 'lab_ready':
                room.ready(pid, message.get('sceneId'), now)
            elif kind == 'lab_load_failed' and room.session and message.get('sceneId') == room.session.scene_id:
                room.session.fail_loading(pid, now)
            elif kind == 'lab_input':
                room.input(pid, message, now)
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, RuntimeError):
        pass
    finally:
        if sender:
            sender.cancel()
            with suppress(Exception, asyncio.CancelledError):
                await sender
        if pid:
            room.disconnect(pid, time.monotonic())


# Build before starting. This avoids exposing any source files or the SQLite DB.
if (ROOT / 'client/dist').is_dir():
    app.mount('/', StaticFiles(directory=ROOT / 'client/dist', html=True), name='lab-client')
