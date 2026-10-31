from fastapi.testclient import TestClient
from server.scenarios.lan import app


def until(ws, predicate):
    for _ in range(160):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError('Expected WebSocket state not received')


def connect(ws, name):
    ws.send_json({'type': 'lab_join', 'name': name})
    return until(ws, lambda m: m['type'] == 'lab_welcome')['playerId']


def test_real_websocket_roster_readiness_movement_and_disconnect(tmp_path, monkeypatch):
    monkeypatch.setenv('SCENARIO_LAB_DB', str(tmp_path / 'lab.sqlite3'))
    with TestClient(app) as client:
        # Shorten only waiting periods; actual transport, simulation and movement
        # use the same code and fixed timestep as a LAN launch.
        app.state.room.definition['queueSeconds'] = .1
        app.state.room.definition['countdownSeconds'] = .1
        app.state.room.definition['resultSeconds'] = .1
        assert client.get('/lab/health').status_code == 200
        with client.websocket_connect('/lab/ws') as a:
            aid = connect(a, 'Alice')
            with client.websocket_connect('/lab/ws') as b:
                bid = connect(b, 'Bob')
                a.send_json({'type': 'lab_queue'})
                b.send_json({'type': 'lab_queue'})
                prepare_a = until(a, lambda m: m.get('phase') == 'loading')
                prepare_b = until(b, lambda m: m.get('phase') == 'loading')
                assert prepare_a['sceneId'] == prepare_b['sceneId']
                scene_id = prepare_a['sceneId']
                assert {p['vehicleType'] for p in prepare_a['players']} == {'car', 'truck'}
                a.send_json({'type': 'lab_ready', 'sceneId': scene_id})
                # Readiness of only one player must not start the room.
                assert until(a, lambda m: m.get('phase') == 'loading')['phase'] == 'loading'
                b.send_json({'type': 'lab_ready', 'sceneId': scene_id})
                state_a = until(a, lambda m: m.get('phase') == 'running')
                until(b, lambda m: m.get('phase') == 'running')
                start = next(p for p in state_a['players'] if p['id'] == aid)
                a.send_json({'type': 'lab_input', 'sceneId': scene_id, 'seq': 1,
                             'throttle': 1, 'steering': 0, 'brake': 0})
                moved_a = until(a, lambda m: any(p['id'] == aid and p['speed'] > 0 for p in m.get('players', [])))
                moved_b = until(b, lambda m: any(p['id'] == aid and p['speed'] > 0 for p in m.get('players', [])))
                assert next(p for p in moved_a['players'] if p['id'] == aid) != start
                assert next(p for p in moved_b['players'] if p['id'] == aid)['speed'] > 0
            cancelled = until(a, lambda m: m.get('phase') == 'cancelled')
            assert cancelled['result']['reason'] == 'participant_disconnected'
            lobby = until(a, lambda m: m.get('phase') == 'lobby')
            assert lobby['returned'] is not None
            assert bid not in {p['id'] for p in lobby['players']}


def test_third_player_gets_tram_and_fourth_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('SCENARIO_LAB_DB', str(tmp_path / 'lab.sqlite3'))
    with TestClient(app) as client:
        app.state.room.definition['queueSeconds'] = .1
        with client.websocket_connect('/lab/ws') as a, client.websocket_connect('/lab/ws') as b, client.websocket_connect('/lab/ws') as c:
            for ws, name in ((a, 'A'), (b, 'B'), (c, 'C')):
                connect(ws, name)
                ws.send_json({'type': 'lab_queue'})
            state = until(a, lambda m: m.get('phase') == 'loading')
            assert {p['vehicleType'] for p in state['players']} == {'car', 'truck', 'tram'}
            with client.websocket_connect('/lab/ws') as fourth:
                fourth.send_json({'type': 'lab_join', 'name': 'Fourth'})
                assert fourth.receive_json()['type'] == 'lab_error'
