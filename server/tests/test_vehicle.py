import math

import pytest

from server.vehicle import Controls, VehicleConfig, VehicleState, step_vehicle

CONFIG = VehicleConfig()


def drive(state, controls, seconds, hz=30):
    for _ in range(round(seconds * hz)):
        state = step_vehicle(state, controls, CONFIG, 1 / hz)
    return state


def test_acceleration_and_distance_are_timestep_independent():
    for hz in (30, 60, 120):
        state = drive(VehicleState(), Controls(throttle=1), 1, hz)
        assert state.speed == pytest.approx(4)
        assert state.z == pytest.approx(2)
        assert state.x == 0


def test_speed_limits_and_brakes_do_not_reverse():
    state = drive(VehicleState(), Controls(throttle=1), 15)
    assert state.speed == CONFIG.maxForwardSpeed
    state = drive(state, Controls(throttle=1, brake=1), 4)
    assert state.speed == 0
    state = drive(state, Controls(brake=1), 3)
    assert state.speed == 0


def test_s_brakes_before_reverse_and_reverse_has_its_own_limit():
    state = VehicleState(speed=4)
    state = drive(state, Controls(throttle=-1), 0.5)
    assert state.speed == pytest.approx(0, abs=1e-9)
    state = drive(state, Controls(throttle=-1), 0.1)
    assert state.speed == 0
    state = drive(state, Controls(throttle=-1), 3)
    assert state.speed == -CONFIG.maxReverseSpeed
    assert state.driveDirection == -1


def test_steering_smooths_centers_and_cannot_rotate_a_stationary_car():
    state = drive(VehicleState(), Controls(steering=1), 1)
    assert state.heading == 0
    assert state.steering == 1
    state = drive(state, Controls(), 0.5)
    assert state.steering == 0
    left = drive(VehicleState(speed=5), Controls(throttle=1, steering=-1), 1)
    right = drive(VehicleState(speed=5), Controls(throttle=1, steering=1), 1)
    assert left.x == pytest.approx(-right.x)
    assert left.heading == pytest.approx(-right.heading)


def test_reverse_turns_in_opposite_direction_and_high_speed_turns_are_bounded():
    reverse = drive(VehicleState(speed=-3, driveDirection=-1), Controls(throttle=-1, steering=1), 0.5)
    assert reverse.heading < 0
    state = VehicleState(speed=CONFIG.maxForwardSpeed, steering=1)
    next_state = step_vehicle(state, Controls(throttle=1, steering=1), CONFIG, 1 / 30)
    lateral_acceleration = state.speed * next_state.heading * 30
    assert lateral_acceleration <= CONFIG.maxLateralAcceleration + 1e-8
    assert -math.pi <= next_state.heading < math.pi


def test_coasting_slows_and_state_is_immutable():
    before = VehicleState(speed=5)
    after = drive(before, Controls(), 1)
    assert before.speed == 5
    assert 0 < after.speed < before.speed


@pytest.mark.parametrize('dt', [0, -1, math.nan, math.inf, 1])
def test_invalid_dt_is_rejected(dt):
    with pytest.raises(ValueError):
        step_vehicle(VehicleState(), Controls(), CONFIG, dt)
