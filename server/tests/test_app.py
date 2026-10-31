import math
import time
import importlib.util
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.state import players


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
    assert not players


def receive_type(ws, message_type):
    for _ in range(100):
        message = ws.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"Expected {message_type}")


def join(ws, name):
    ws.send_json({"type": "join", "name": name, "v": 1})
    return receive_type(ws, "welcome")


def test_two_players_exchange_state_and_disconnect(client):
    with client.websocket_connect("/ws") as first:
        welcome1 = join(first, " Alice ")
        assert welcome1["players"] == []
        with client.websocket_connect("/ws") as second:
            welcome2 = join(second, "Bob")
            assert welcome2["id"] != welcome1["id"]
            assert welcome2["players"][0]["name"] == "Alice"
            assert receive_type(first, "player_joined")["id"] == welcome2["id"]
            second.send_json({"type": "state", "x": 1.256, "z": -3.4, "heading": 1.57, "future": True})
            for _ in range(100):
                snapshot = receive_type(first, "snapshot")
                other = next(p for p in snapshot["players"] if p["id"] == welcome2["id"])
                if other["x"] == 1.26:
                    break
            assert other == {"id": welcome2["id"], "x": 1.26, "z": -3.4, "heading": 1.57}
            next_snapshot = receive_type(first, "snapshot")
            assert next_snapshot["tick"] > snapshot["tick"]
        assert receive_type(first, "player_left")["id"] == welcome2["id"]


def test_join_required_and_protocol_errors_do_not_break_connection(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "state", "x": 1, "z": 0, "heading": 0})
        assert receive_type(ws, "error")["code"] == "not_joined"
        ws.send_text("not json")
        assert receive_type(ws, "error")["code"] == "bad_message"
        ws.send_json({"type": "join", "name": " " * 3, "v": 1})
        assert receive_type(ws, "error")["code"] == "bad_value"
        welcome = join(ws, "Alice")
        ws.send_json({"type": "future_message"})
        assert receive_type(ws, "error")["code"] == "unknown_type"
        ws.send_json({"type": "state", "x": 1})
        assert receive_type(ws, "error")["code"] == "bad_message"
        ws.send_json({"type": "join", "name": "Bob", "v": 1})
        assert receive_type(ws, "error")["code"] == "already_joined"
        assert welcome["id"] in players


@pytest.mark.parametrize("value", [True, "1", None, math.nan, math.inf, 10**400])
def test_invalid_coordinates_do_not_change_state(client, value):
    with client.websocket_connect("/ws") as ws:
        welcome = join(ws, "Alice")
        ws.send_json({"type": "state", "x": value, "z": 0, "heading": 0})
        assert receive_type(ws, "error")["code"] == "bad_value"
        assert players[welcome["id"]]["x"] == welcome["x"]


@pytest.mark.parametrize("version", [True, 2, "1"])
def test_bad_protocol_version(client, version):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "join", "name": "Alice", "v": version})
        assert receive_type(ws, "error")["code"] == "bad_version"
    assert not players


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_vehicle_input_moves_on_server_and_timeout_brakes(client):
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'join', 'name': 'Driver', 'v': 1, 'controlMode': 'vehicle'})
        welcome = receive_type(ws, 'welcome')
        assert welcome['controlMode'] == 'vehicle'
        player = players[welcome['id']]
        for seq in range(1, 11):
            ws.send_json({'type': 'input', 'sceneId': welcome['sceneId'], 'epoch': welcome['epoch'],
                          'seq': seq, 'throttle': 1, 'steering': 0, 'brake': 0})
            time.sleep(0.05)
        assert player['vehicle'].speed > 1
        assert player['z'] > welcome['z']
        ws.send_json({'type': 'input', 'sceneId': welcome['sceneId'], 'epoch': 0,
                      'seq': 100, 'throttle': 1, 'steering': 0, 'brake': 0})
        ws.send_json({'type': 'input', 'sceneId': welcome['sceneId'], 'epoch': 1,
                      'seq': 1, 'throttle': 1, 'steering': 0, 'brake': 0})
        ws.send_json({'type': 'state', 'x': 100, 'z': 100, 'heading': 0})
        assert receive_type(ws, 'error')['code'] == 'bad_value'
        assert player['input_seq'] == 10
        for _ in range(60):
            snapshot = receive_type(ws, 'snapshot')
            if player['vehicle'].speed == 0:
                break
        assert player['vehicle'].speed == 0
        assert next(p for p in snapshot['players'] if p['id'] == welcome['id'])['z'] > 0


def test_server_can_start_before_client_is_built():
    spec = importlib.util.spec_from_file_location("server.unbuilt_test", "server/app.py")
    module = importlib.util.module_from_spec(spec)
    with patch("pathlib.Path.is_dir", return_value=False):
        # Load another app instance without changing the application's source files.
        spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        assert client.get("/").json()["status"] == "client_not_built"
        assert client.get("/health").status_code == 200
