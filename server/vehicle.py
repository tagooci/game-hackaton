"""Аркадная физика автомобиля на плоскости. Не зависит от сети и графики."""

from dataclasses import dataclass, replace
import math


@dataclass(frozen=True)
class VehicleConfig:
    wheelbase: float = 2.6
    maxForwardSpeed: float = 22.0
    maxReverseSpeed: float = 4.0
    acceleration: float = 4.0
    brakeDeceleration: float = 8.0
    rollingDeceleration: float = 0.45
    maxSteerAngle: float = 0.6
    steeringRate: float = 3.0
    maxLateralAcceleration: float = 5.5
    directionChangeDelay: float = 0.25


@dataclass(frozen=True)
class Controls:
    throttle: float = 0.0
    steering: float = 0.0
    brake: float = 0.0


@dataclass(frozen=True)
class VehicleState:
    x: float = 0.0
    z: float = 0.0
    heading: float = 0.0
    speed: float = 0.0
    steering: float = 0.0
    driveDirection: int = 1
    directionChangeTime: float = 0.0


def approach(value: float, target: float, amount: float) -> float:
    return value + max(-amount, min(amount, target - value))


def step_vehicle(state: VehicleState, controls: Controls, config: VehicleConfig, dt: float) -> VehicleState:
    """Один шаг в секундах. Возвращает новое состояние, не изменяя исходное."""
    if not math.isfinite(dt) or dt <= 0 or dt > 0.1:
        raise ValueError("Physics dt must be finite and within (0, 0.1]")
    valid_axes = all(math.isfinite(v) and -1 <= v <= 1 for v in (controls.throttle, controls.steering))
    valid_brake = math.isfinite(controls.brake) and 0 <= controls.brake <= 1
    if not valid_axes or not valid_brake:
        raise ValueError("Controls outside their allowed ranges")

    steering = approach(state.steering, controls.steering, config.steeringRate * dt)
    speed = state.speed
    direction = state.driveDirection
    change_time = 0.0
    desired_direction = 1 if controls.throttle >= 0 else -1

    if controls.brake > 0:
        speed = approach(speed, 0, config.brakeDeceleration * controls.brake * dt)
    elif controls.throttle == 0:
        speed = approach(speed, 0, config.rollingDeceleration * dt)
    elif desired_direction != direction:
        # Сначала остановка, затем короткая задержка перед сменой направления.
        speed = approach(speed, 0, config.brakeDeceleration * abs(controls.throttle) * dt)
        if abs(state.speed) < 0.01:
            change_time = state.directionChangeTime + dt
            if change_time >= config.directionChangeDelay:
                direction = desired_direction
                change_time = 0.0
    else:
        speed += controls.throttle * config.acceleration * dt
        speed = max(-config.maxReverseSpeed, min(config.maxForwardSpeed, speed))

    # На скорости уменьшаем угол колёс, чтобы машина не разворачивалась резко.
    speed_limit = math.atan(config.maxLateralAcceleration * config.wheelbase / max(speed * speed, 0.01))
    turn_limit = min(config.maxSteerAngle, speed_limit)
    wheel_angle = steering * turn_limit
    distance = (state.speed + speed) * 0.5 * dt
    turn = distance / config.wheelbase * math.tan(wheel_angle)
    midpoint_heading = state.heading + turn * 0.5

    return replace(
        state,
        x=state.x + math.sin(midpoint_heading) * distance,
        z=state.z + math.cos(midpoint_heading) * distance,
        heading=(state.heading + turn + math.pi) % (2 * math.pi) - math.pi,
        speed=speed,
        steering=steering,
        driveDirection=direction,
        directionChangeTime=change_time,
    )
