import importlib
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from server.db import Database
from server.auth import AuthService

module = importlib.import_module('server.app')


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = Database(tmp_path / 'test.sqlite3')
    monkeypatch.setattr(module, 'database', db)
    monkeypatch.setattr(module, 'auth', AuthService(db))
    with TestClient(module.app) as client:
        yield client
    assert not module.v2_players


def receive(ws, kind):
    for _ in range(100):
        message = ws.receive_json()
        if message['type'] == kind:
            return message
    raise AssertionError(kind)


def register(client, username='alice'):
    response = client.post('/api/v2/register', json={'username': username, 'password': 'password123', 'name': username})
    assert response.status_code == 200
    return response.json()


def ready(ws):
    ws.send_json({'type': 'join', 'v': 2})
    welcome = receive(ws, 'welcome')
    prepare = receive(ws, 'scene_prepare')
    ws.send_json({'type': 'scene_ready', 'sceneId': prepare['sceneId'], 'epoch': prepare['epoch'], 'revision': prepare['plan']['revision']})
    receive(ws, 'scene_start')
    receive(ws, 'snapshot')
    return welcome, prepare


def input_message(seq=1, **extra):
    return {'type': 'input', 'sceneId': 'world:main', 'epoch': 1, 'seq': seq, 'throttle': 1, 'steering': 0, 'brake': 0, **extra}


def test_auth_validation_cookie_bootstrap_and_logout(client):
    assert client.get('/api/v2/me').status_code == 401
    assert client.get('/api/v2/content/bootstrap').status_code == 401
    assert client.post('/api/v2/register', json={'username': 'a', 'password': 'short'}).status_code == 400
    account = register(client)
    assert 'HttpOnly' in str(client.cookies) or client.cookies.get('game_session')
    assert client.get('/api/v2/me').json() == account
    assert client.post('/api/v2/register', json={'username': 'alice', 'password': 'password123'}).status_code == 409
    assert client.post('/api/v2/login', json={'username': 'alice', 'password': 'incorrect'}).status_code == 401
    assert client.post('/api/v2/login', json={'username': 'alice', 'password': 'password123'}).status_code == 200
    bootstrap = client.get('/api/v2/content/bootstrap').json()
    assert bootstrap['worldBytes'] == module.WORLD_MAP['worldBytes'] + sum(r['bytes'] for r in module.world_resources())
    assert bootstrap['cacheBudgetBytes'] == bootstrap['worldBytes'] // 10
    client.post('/api/v2/logout')
    assert client.get('/api/v2/me').status_code == 401
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect('/ws/v2') as ws:
            ws.receive_json()
    assert error.value.code == 1008


def test_v2_physics_validation_timeout_and_saved_position(client):
    account = register(client)
    with client.websocket_connect('/ws/v2') as ws:
        welcome, plan = ready(ws)
        assert welcome['playerId'] == account['playerId']
        assert len(plan['plan']['resources']) == 2
        first = receive(ws, 'snapshot')['players'][0]
        assert 0 <= first['color'] < 5
        assert first['wheelAngle'] == 0
        ws.send_json(input_message(epoch=99))
        ws.send_json(input_message(throttle=2))
        assert receive(ws, 'error')['code'] == 'bad_value'
        ws.send_json(input_message())
        time.sleep(0.15)
        state = module.v2_players[account['playerId']]
        assert (state['vehicle'].x,state['vehicle'].z) != (module.WORLD_MAP['spawn']['x'],module.WORLD_MAP['spawn']['z'])
        ws.send_json(input_message(throttle=-1))  # Duplicate seq cannot overwrite accepted input.
        time.sleep(0.03)
        assert state['controls'].throttle == 1
        assert state['seq'] == 1
        time.sleep(0.8)
        assert state['vehicle'].speed == 0
        assert state['applied_seq'] == 1
        saved_x = state['vehicle'].x
        saved_z = state['vehicle'].z
    with client.websocket_connect('/ws/v2') as ws:
        _, plan = ready(ws)
        assert plan['spawn']['x'] == pytest.approx(saved_x)
        assert plan['spawn']['z'] == pytest.approx(saved_z)
        assert plan['mapId'] == module.WORLD_MAP['worldId']
        assert plan['plan']['mapManifestUrl'] == '/content/world/manifest.json'
        assert module.v2_players[account['playerId']]['seq'] == 0


def moved_from_spawn(player):
    return abs(player['x']-module.WORLD_MAP['spawn']['x']) + abs(player['z']-module.WORLD_MAP['spawn']['z']) > .001


def test_two_accounts_full_snapshots_and_disconnect(client):
    alice = register(client)
    alice_cookie = client.cookies.get('game_session')
    bob = register(client, 'bobby')
    bob_cookie = client.cookies.get('game_session')
    with client.websocket_connect('/ws/v2', headers={'cookie': f'game_session={alice_cookie}'}) as a:
        ready(a)
        with client.websocket_connect('/ws/v2', headers={'cookie': f'game_session={bob_cookie}'}) as b:
            ready(b)
            snapshot = receive(a, 'snapshot')
            assert {p['id'] for p in snapshot['players']} == {alice['playerId'], bob['playerId']}
            b.send_json(input_message())
            for _ in range(20):
                snapshot = receive(a, 'snapshot')
                if moved_from_spawn(next(p for p in snapshot['players'] if p['id'] == bob['playerId'])):
                    break
            assert moved_from_spawn(next(p for p in snapshot['players'] if p['id'] == bob['playerId']))
        for _ in range(20):
            if {p['id'] for p in receive(a, 'snapshot')['players']} == {alice['playerId']}:
                break
        else:
            pytest.fail('Disconnected car remains visible')


def test_scene_gate_rate_limit_and_duplicate_connection(client):
    register(client)
    with client.websocket_connect('/ws/v2') as ws:
        ws.send_json({'type': 'join', 'v': 2})
        receive(ws, 'welcome')
        receive(ws, 'scene_prepare')
        ws.send_json(input_message())
        time.sleep(0.1)
        assert next(iter(module.v2_players.values()))['vehicle'].x == module.WORLD_MAP['spawn']['x']
        for _ in range(65):
            ws.send_json(input_message())
        assert receive(ws, 'error')['code'] == 'rate_limited'
    with client.websocket_connect('/ws/v2') as old:
        ready(old)
        with client.websocket_connect('/ws/v2') as new:
            ready(new)
            with pytest.raises(WebSocketDisconnect) as error:
                for _ in range(20):
                    old.receive_json()
            assert error.value.code == 4001
            assert len(module.v2_players) == 1


def test_new_player_spawn_and_respawn_reloads_scene_and_rejects_old_input(client):
    account = register(client)
    with client.websocket_connect('/ws/v2') as ws:
        _, first = ready(ws)
        assert first['spawn']['x'] == module.WORLD_MAP['spawn']['x']
        assert first['spawn']['z'] == module.WORLD_MAP['spawn']['z']
        assert first['spawn']['y'] == pytest.approx(module.WORLD_MAP['spawnY'])
        ws.send_json(input_message())
        time.sleep(.15)
        player = module.v2_players[account['playerId']]
        assert player['vehicle'].speed > 0
        ws.send_json({'type': 'respawn', 'sceneId': 'world:main', 'epoch': 1})
        plan = receive(ws, 'scene_prepare')
        assert plan['epoch'] == 2
        assert plan['spawn'] == first['spawn']
        assert player['vehicle'].speed == 0
        assert account['playerId'] not in module.v2_scene_ready
        ws.send_json(input_message(seq=100))
        time.sleep(.1)
        assert player['seq'] == 0
        assert player['vehicle'].speed == 0
        ws.send_json({'type': 'scene_ready', 'sceneId': 'world:main', 'epoch': 2, 'revision': 1})
        receive(ws, 'scene_start')
        assert receive(ws, 'snapshot')['epoch'] == 2
        ws.send_json(input_message(seq=101))  # Previous epoch remains invalid after ready.
        ws.send_json(input_message(epoch=2))
        time.sleep(.1)
        assert player['seq'] == 1
        assert player['vehicle'].speed > 0


def test_respawn_is_rejected_in_scenario(client):
    account = register(client)
    with client.websocket_connect('/ws/v2') as ws:
        ready(ws)
        player = module.v2_players[account['playerId']]
        player['sceneKind'] = 'scenario'
        before = player['vehicle']
        ws.send_json({'type': 'respawn', 'sceneId': 'world:main', 'epoch': 1})
        assert receive(ws, 'error')['code'] == 'respawn_forbidden'
        assert player['vehicle'] == before
        assert player['epoch'] == 1
