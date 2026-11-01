"""Geometry-based rule checks for scenario participants."""

from dataclasses import dataclass, field
import math


Point = tuple[float, float]


@dataclass(frozen=True)
class LaneRule:
    id: str
    centerline: tuple[Point, ...]
    width: float


@dataclass(frozen=True)
class StopLineRule:
    id: str
    from_point: Point
    to_point: Point
    required_stop_speed: float = 0.5


@dataclass(frozen=True)
class ScenarioRuleConfig:
    speed_limit: float | None = None
    lanes: tuple[LaneRule, ...] = ()
    stop_lines: tuple[StopLineRule, ...] = ()
    lane_tolerance: float = 0.25
    role_rules: dict[str, "ScenarioRuleConfig"] = field(default_factory=dict)


@dataclass
class ScenarioRuleEngine:
    configs: dict[str, ScenarioRuleConfig] = field(default_factory=dict)

    def register(self, scenario_id: str, config: ScenarioRuleConfig) -> None:
        if scenario_id in self.configs:
            raise ValueError(f"duplicate rule config: {scenario_id}")
        self._validate(config)
        self.configs[scenario_id] = config

    def evaluate(
        self,
        scenario_id: str,
        role_id: str | None,
        previous: tuple[float, float, float],
        current: tuple[float, float, float],
    ) -> tuple[str, ...]:
        config = self.configs.get(scenario_id)
        if config is None:
            return ()
        if role_id is not None:
            config = config.role_rules.get(role_id, config)
        previous_x, previous_z, previous_speed = previous
        current_x, current_z, current_speed = current
        violations: list[str] = []
        if (
            config.speed_limit is not None
            and abs(current_speed) > config.speed_limit
        ):
            violations.append("speed_limit")
        if config.lanes and not any(
            _distance_to_polyline(current_x, current_z, lane.centerline)
            <= lane.width / 2 + config.lane_tolerance
            for lane in config.lanes
        ):
            violations.append("lane_departure")
        for stop_line in config.stop_lines:
            if _segments_intersect(
                (previous_x, previous_z),
                (current_x, current_z),
                stop_line.from_point,
                stop_line.to_point,
            ) and abs(previous_speed) > stop_line.required_stop_speed:
                violations.append(f"stop_line:{stop_line.id}")
        return tuple(violations)

    @staticmethod
    def _validate(config: ScenarioRuleConfig) -> None:
        values = [config.speed_limit, config.lane_tolerance]
        if any(value is not None and (not math.isfinite(value) or value < 0) for value in values):
            raise ValueError("rule limits must be finite and non-negative")
        for lane in config.lanes:
            if len(lane.centerline) < 2 or not math.isfinite(lane.width) or lane.width <= 0:
                raise ValueError(f"invalid lane rule: {lane.id}")
        for stop_line in config.stop_lines:
            if stop_line.required_stop_speed < 0 or not math.isfinite(stop_line.required_stop_speed):
                raise ValueError(f"invalid stop line rule: {stop_line.id}")
        for role_id, role_config in config.role_rules.items():
            if not role_id:
                raise ValueError("role rule id must not be empty")
            ScenarioRuleEngine._validate(role_config)


def _distance_to_polyline(x: float, z: float, points: tuple[Point, ...]) -> float:
    return min(
        _distance_to_segment((x, z), start, end)
        for start, end in zip(points, points[1:])
    )


def _distance_to_segment(point: Point, start: Point, end: Point) -> float:
    dx, dz = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dz * dz
    if length_squared == 0:
        return math.dist(point, start)
    projection = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dz)
            / length_squared,
        ),
    )
    return math.dist(point, (start[0] + projection * dx, start[1] + projection * dz))


def _segments_intersect(first_start: Point, first_end: Point, second_start: Point, second_end: Point) -> bool:
    def orientation(a: Point, b: Point, c: Point) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    first = orientation(first_start, first_end, second_start)
    second = orientation(first_start, first_end, second_end)
    third = orientation(second_start, second_end, first_start)
    fourth = orientation(second_start, second_end, first_end)
    return ((first > 0) != (second > 0)) and ((third > 0) != (fourth > 0))
