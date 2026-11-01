"""Parser for completed scenario results received from the game server."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import math
from typing import Any


class ScenarioType(StrEnum):
    SHORT = "short"
    LONG = "long"


class ScenarioStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class CheckName(StrEnum):
    ROAD_MARKINGS = "roadMarkings"
    RIGHT_OF_WAY = "rightOfWay"
    TRAFFIC_SIGNS = "trafficSigns"
    COLLISIONS = "collisions"


class ResultParseError(ValueError):
    """Raised when an incoming agent result does not match the contract."""


@dataclass(frozen=True)
class CheckResult:
    checked: bool
    violation_count: int | None


@dataclass(frozen=True)
class ViolationPosition:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Violation:
    id: str
    category: CheckName
    rule_id: str
    time_ms: int
    position: ViolationPosition | None
    related_player_ids: tuple[str, ...]
    sign_id: str | None
    details: str


@dataclass(frozen=True)
class ScenarioResult:
    schema_version: int
    result_id: str
    session_id: str
    scenario_id: str
    scenario_version: int
    scenario_type: ScenarioType
    player_id: str
    role_id: str
    status: ScenarioStatus
    duration_ms: int
    checks: dict[CheckName, CheckResult]
    violations: tuple[Violation, ...]


def parse_result_json(payload: str | bytes) -> ScenarioResult:
    try:
        value = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ResultParseError("result must contain valid JSON") from exc
    return parse_result(value)


def parse_result(value: Any) -> ScenarioResult:
    if not isinstance(value, dict):
        raise ResultParseError("result must be a JSON object")

    schema_version = _required_int(value, "schemaVersion", minimum=1)
    if schema_version != 1:
        raise ResultParseError(f"unsupported schemaVersion: {schema_version}")

    scenario = _required_object(value, "scenario")
    checks_value = _required_object(value, "checks")
    violations_value = value.get("violations")
    if not isinstance(violations_value, list):
        raise ResultParseError("violations must be an array")

    checks: dict[CheckName, CheckResult] = {}
    for name in CheckName:
        raw_check = checks_value.get(name.value)
        if not isinstance(raw_check, dict):
            raise ResultParseError(f"checks.{name.value} must be an object")
        checked = _required_bool(raw_check, "checked")
        violation_count = raw_check.get("violationCount")
        if not checked:
            if violation_count is not None:
                raise ResultParseError(
                    f"checks.{name.value}.violationCount must be null when unchecked"
                )
        elif not _is_non_negative_int(violation_count):
            raise ResultParseError(
                f"checks.{name.value}.violationCount must be a non-negative integer"
            )
        checks[name] = CheckResult(checked, violation_count)

    violations = tuple(_parse_violation(item, index) for index, item in enumerate(violations_value))
    _validate_counts(checks, violations)

    return ScenarioResult(
        schema_version=schema_version,
        result_id=_required_string(value, "resultId"),
        session_id=_required_string(value, "sessionId"),
        scenario_id=_required_string(scenario, "id"),
        scenario_version=_required_int(scenario, "version", minimum=1),
        scenario_type=_enum_value(ScenarioType, scenario, "type"),
        player_id=_required_string(value, "playerId"),
        role_id=_required_string(value, "roleId"),
        status=_enum_value(ScenarioStatus, value, "status"),
        duration_ms=_required_int(value, "durationMs", minimum=0),
        checks=checks,
        violations=violations,
    )


def _parse_violation(value: Any, index: int) -> Violation:
    if not isinstance(value, dict):
        raise ResultParseError(f"violations[{index}] must be an object")
    position_value = value.get("position")
    position = None
    if position_value is not None:
        if not isinstance(position_value, dict):
            raise ResultParseError(f"violations[{index}].position must be an object or null")
        position = ViolationPosition(
            _required_finite_number(position_value, "x"),
            _required_finite_number(position_value, "y"),
            _required_finite_number(position_value, "z"),
        )
    related = value.get("relatedPlayerIds", [])
    if not isinstance(related, list) or not all(isinstance(item, str) for item in related):
        raise ResultParseError(f"violations[{index}].relatedPlayerIds must be an array of strings")
    sign_id = value.get("signId")
    if sign_id is not None and not isinstance(sign_id, str):
        raise ResultParseError(f"violations[{index}].signId must be a string or null")
    return Violation(
        id=_required_string(value, "id"),
        category=_enum_value(CheckName, value, "category"),
        rule_id=_required_string(value, "ruleId"),
        time_ms=_required_int(value, "timeMs", minimum=0),
        position=position,
        related_player_ids=tuple(related),
        sign_id=sign_id,
        details=_required_string(value, "details"),
    )


def _validate_counts(checks: dict[CheckName, CheckResult], violations: tuple[Violation, ...]) -> None:
    counts = {name: 0 for name in CheckName}
    for violation in violations:
        counts[violation.category] += 1
    for name, check in checks.items():
        if check.checked and check.violation_count != counts[name]:
            raise ResultParseError(
                f"checks.{name.value}.violationCount does not match violations"
            )


def _required_object(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ResultParseError(f"{key} must be an object")
    return result


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ResultParseError(f"{key} must be a non-empty string")
    return result


def _required_bool(value: dict[str, Any], key: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        raise ResultParseError(f"{key} must be a boolean")
    return result


def _required_int(value: dict[str, Any], key: str, *, minimum: int) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < minimum:
        raise ResultParseError(f"{key} must be an integer >= {minimum}")
    return result


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _required_finite_number(value: dict[str, Any], key: str) -> float:
    result = value.get(key)
    if not isinstance(result, (int, float)) or isinstance(result, bool) or not math.isfinite(result):
        raise ResultParseError(f"{key} must be a finite number")
    return float(result)


def _enum_value(enum_type: type[StrEnum], value: dict[str, Any], key: str) -> Any:
    raw = value.get(key)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise ResultParseError(f"invalid {key}: {raw!r}") from exc
