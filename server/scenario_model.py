"""Server-side state machine for multiplayer driving scenarios.

The registry is intentionally data-driven. Map-specific zones and role spawns
are added after the next map import; the lifecycle does not depend on Blender.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import count
import math
import secrets
import time
from typing import Any

from .scenario_rules import ScenarioRuleConfig
from .scenario_rules import ScenarioRuleEngine


def _finite_triplet(value: tuple[float, float, float]) -> bool:
    return len(value) == 3 and all(math.isfinite(item) for item in value)


def _validate_zone(zone: ScenarioZone) -> None:
    values = (zone.min_x, zone.max_x, zone.min_z, zone.max_z, zone.required_speed)
    if not zone.id.strip() or not all(math.isfinite(value) for value in values):
        raise ValueError(f"invalid scenario zone: {zone.id}")
    if zone.min_x > zone.max_x or zone.min_z > zone.max_z or zone.required_speed < 0:
        raise ValueError(f"invalid scenario zone bounds: {zone.id}")


def _validate_rule_config(config: ScenarioRuleConfig, role_ids: set[str]) -> None:
    unknown_roles = set(config.role_rules) - role_ids
    if unknown_roles:
        raise ValueError(f"rule config references unknown roles: {sorted(unknown_roles)}")
    ScenarioRuleEngine._validate(config)


class ScenarioState(StrEnum):
    WAITING = "waiting"
    LOADING = "loading"
    COUNTDOWN = "countdown"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ScenarioZone:
    id: str
    min_x: float
    max_x: float
    min_z: float
    max_z: float
    required_speed: float = 0.5
    require_stop: bool = True

    def contains(self, x: float, z: float, speed: float) -> bool:
        return (
            self.min_x <= x <= self.max_x
            and self.min_z <= z <= self.max_z
            and (not self.require_stop or abs(speed) <= self.required_speed)
        )


@dataclass(frozen=True)
class ScenarioRole:
    id: str
    vehicle_type: str = "car"
    spawn: tuple[float, float, float] = (0.0, 0.0, 0.0)
    destination: ScenarioZone | None = None


@dataclass(frozen=True)
class ScenarioDefinition:
    id: str
    map_id: str
    zone: ScenarioZone
    roles: tuple[ScenarioRole, ...]
    return_spawn: tuple[float, float, float] = (0.0, 0.0, 0.0)
    time_limit_seconds: float = 60.0
    participation_xp: int = 10
    completion_xp: int = 100
    perfect_bonus_xp: int = 50
    violation_penalty_xp: int = 15
    maximum_xp: int = 150
    rule_config: ScenarioRuleConfig = field(default_factory=ScenarioRuleConfig)

    @property
    def min_players(self) -> int:
        return len(self.roles)


@dataclass
class Candidate:
    player_id: str
    ready_at: float


@dataclass
class ScenarioSession:
    id: str
    definition: ScenarioDefinition
    participants: dict[str, str]
    state: ScenarioState = ScenarioState.LOADING
    started_at: float | None = None
    violations: dict[str, list[str]] = field(default_factory=dict)
    finished_players: set[str] = field(default_factory=set)
    ready_players: set[str] = field(default_factory=set)
    start_tick: int | None = None
    xp: dict[str, int] = field(default_factory=dict)
    result_id: str | None = None


@dataclass(frozen=True)
class ScenarioEvent:
    type: str
    scenario_id: str
    session_id: str | None
    player_id: str | None = None
    waiting: int | None = None
    required: int | None = None
    role_id: str | None = None
    reason: str | None = None
    passed: bool | None = None
    violation_ids: tuple[str, ...] = ()
    start_tick: int | None = None
    xp: int | None = None
    result_id: str | None = None


class ScenarioManager:
    def __init__(self, definitions: tuple[ScenarioDefinition, ...] = ()):
        self.definitions: dict[str, ScenarioDefinition] = {}
        self.candidates: dict[str, list[Candidate]] = {}
        self.sessions: dict[str, ScenarioSession] = {}
        self.player_sessions: dict[str, str] = {}
        self._session_ids = count(1)
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ScenarioDefinition) -> None:
        if definition.id in self.definitions:
            raise ValueError(f"duplicate scenario: {definition.id}")
        self._validate_definition(definition)
        self.definitions[definition.id] = definition

    @staticmethod
    def _validate_definition(definition: ScenarioDefinition) -> None:
        if not definition.id.strip() or not definition.map_id.strip():
            raise ValueError("scenario id and map id must not be empty")
        if len(definition.roles) < 2:
            raise ValueError("a scenario needs at least two roles")
        if len(definition.roles) > 3:
            raise ValueError("a scenario supports at most three roles")
        role_ids = [role.id for role in definition.roles]
        if any(not role_id.strip() for role_id in role_ids):
            raise ValueError("role ids must not be empty")
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("role ids must be unique")
        _validate_zone(definition.zone)
        if not _finite_triplet(definition.return_spawn):
            raise ValueError("return spawn must contain finite coordinates")
        zone_ids = {definition.zone.id}
        spawn_points: set[tuple[float, float, float]] = set()
        for role in definition.roles:
            if not _finite_triplet(role.spawn):
                raise ValueError(f"invalid spawn for role: {role.id}")
            if role.spawn in spawn_points:
                raise ValueError("role spawn points must be unique")
            spawn_points.add(role.spawn)
            if role.destination is None:
                raise ValueError(f"role needs a destination: {role.id}")
            _validate_zone(role.destination)
            if role.destination.id in zone_ids:
                raise ValueError(f"zone ids must be unique: {role.destination.id}")
            zone_ids.add(role.destination.id)
        _validate_rule_config(definition.rule_config, set(role_ids))
        if not math.isfinite(definition.time_limit_seconds) or definition.time_limit_seconds <= 0:
            raise ValueError("time limit must be positive and finite")
        if any(value < 0 for value in (
            definition.participation_xp,
            definition.completion_xp,
            definition.perfect_bonus_xp,
            definition.violation_penalty_xp,
        )):
            raise ValueError("experience values must be non-negative")
        if definition.maximum_xp < 0:
            raise ValueError("maximum experience must be non-negative")

    def join(self, player_id: str, scenario_id: str, x: float, z: float, speed: float, now: float) -> list[ScenarioEvent]:
        definition = self.definitions.get(scenario_id)
        if definition is None:
            return [ScenarioEvent("scenario_error", scenario_id, None, player_id, reason="unknown_scenario")]
        if player_id in self.player_sessions:
            return [ScenarioEvent("scenario_error", scenario_id, None, player_id, reason="already_in_scenario")]
        if not definition.zone.contains(x, z, speed):
            return [ScenarioEvent("scenario_error", scenario_id, None, player_id, reason="outside_zone")]

        candidates = self.candidates.setdefault(scenario_id, [])
        if any(candidate.player_id == player_id for candidate in candidates):
            return [ScenarioEvent("scenario_error", scenario_id, None, player_id, reason="already_waiting")]
        candidates.append(Candidate(player_id, now))
        candidates.sort(key=lambda candidate: (candidate.ready_at, candidate.player_id))
        if len(candidates) < definition.min_players:
            return [ScenarioEvent(
                "scenario_waiting", scenario_id, None, player_id,
                waiting=len(candidates), required=definition.min_players,
            )]

        selected = candidates[:definition.min_players]
        del candidates[:definition.min_players]
        session_id = f"scenario:{next(self._session_ids)}"
        participants = {
            candidate.player_id: role.id
            for candidate, role in zip(selected, definition.roles, strict=True)
        }
        session = ScenarioSession(session_id, definition, participants)
        self.sessions[session_id] = session
        for participant_id in participants:
            self.player_sessions[participant_id] = session_id
        return [
            ScenarioEvent("scenario_assigned", scenario_id, session_id, participant_id, role_id=role_id)
            for participant_id, role_id in participants.items()
        ]

    def leave(self, player_id: str, reason: str = "participant_left") -> list[ScenarioEvent]:
        for scenario_id, candidates in self.candidates.items():
            remaining = [candidate for candidate in candidates if candidate.player_id != player_id]
            if len(remaining) != len(candidates):
                self.candidates[scenario_id] = remaining
                definition = self.definitions[scenario_id]
                return [ScenarioEvent(
                    "scenario_waiting", scenario_id, None, player_id,
                    waiting=len(remaining), required=definition.min_players,
                )]

        session_id = self.player_sessions.pop(player_id, None)
        if session_id is None:
            return []
        return self.cancel(session_id, reason)

    def cancel(self, session_id: str, reason: str) -> list[ScenarioEvent]:
        session = self.sessions[session_id]
        if session.state in (ScenarioState.CANCELLED, ScenarioState.FINISHED):
            return []
        session.state = ScenarioState.CANCELLED
        for participant_id in session.participants:
            self.player_sessions.pop(participant_id, None)
        return [ScenarioEvent(
            "scenario_cancelled", session.definition.id, session.id,
            reason=reason,
        )]

    def release(self, session_id: str) -> None:
        session = self.sessions[session_id]
        for participant_id in session.participants:
            self.player_sessions.pop(participant_id, None)

    def discard(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is not None:
            for participant_id in session.participants:
                self.player_sessions.pop(participant_id, None)

    def set_state(self, session_id: str, state: ScenarioState, now: float | None = None) -> None:
        session = self.sessions[session_id]
        if state == ScenarioState.RUNNING:
            session.started_at = now
        session.state = state

    def mark_ready(self, session_id: str, player_id: str, start_tick: int) -> list[ScenarioEvent]:
        session = self.sessions[session_id]
        if player_id not in session.participants or session.state != ScenarioState.LOADING:
            return []
        session.ready_players.add(player_id)
        if session.ready_players != set(session.participants):
            return []
        session.state = ScenarioState.RUNNING
        session.start_tick = start_tick
        session.started_at = time.monotonic()
        return [
            ScenarioEvent(
                "scenario_start",
                session.definition.id,
                session.id,
                participant_id,
                role_id=session.participants[participant_id],
                start_tick=start_tick,
            )
            for participant_id in session.participants
        ]

    def observe(
        self,
        player_id: str,
        x: float,
        z: float,
        speed: float,
    ) -> list[ScenarioEvent]:
        """Record destination arrival and finish once every role arrives."""
        session_id = self.player_sessions.get(player_id)
        if session_id is None:
            return []
        session = self.sessions[session_id]
        if session.state != ScenarioState.RUNNING or player_id in session.finished_players:
            return []
        definition = session.definition
        role_id = session.participants[player_id]
        role = next(role for role in session.definition.roles if role.id == role_id)
        if role.destination is None or not role.destination.contains(x, z, speed):
            return []

        session.finished_players.add(player_id)
        violations = tuple(session.violations.get(player_id, ()))
        xp = definition.participation_xp + definition.completion_xp
        xp += 0 if violations else definition.perfect_bonus_xp
        xp -= len(violations) * definition.violation_penalty_xp
        session.xp[player_id] = max(0, min(definition.maximum_xp, xp))
        events = [ScenarioEvent(
            "scenario_player_finished",
            session.definition.id,
            session.id,
            player_id,
            role_id=role_id,
            passed=not violations,
            violation_ids=violations,
            xp=session.xp[player_id],
        )]
        if len(session.finished_players) == len(session.participants):
            session.state = ScenarioState.FINISHED
            session.result_id = f"result-{secrets.token_urlsafe(12)}"
            events.append(ScenarioEvent(
                "scenario_result",
                session.definition.id,
                session.id,
                reason="all_players_finished",
                result_id=session.result_id,
            ))
        return events

    def expire(self, now: float | None = None) -> list[ScenarioEvent]:
        current_time = time.monotonic() if now is None else now
        events: list[ScenarioEvent] = []
        for session in self.sessions.values():
            if (
                session.state != ScenarioState.RUNNING
                or session.started_at is None
                or current_time - session.started_at < session.definition.time_limit_seconds
            ):
                continue
            session.state = ScenarioState.CANCELLED
            for participant_id in session.participants:
                self.player_sessions.pop(participant_id, None)
            events.append(ScenarioEvent(
                "scenario_cancelled",
                session.definition.id,
                session.id,
                reason="time_limit",
            ))
        return events

    def session_for_player(self, player_id: str) -> ScenarioSession | None:
        session_id = self.player_sessions.get(player_id)
        return self.sessions.get(session_id) if session_id is not None else None

    def record_violation(self, session_id: str, player_id: str, event_id: str) -> None:
        session = self.sessions[session_id]
        if player_id not in session.participants:
            raise ValueError("player is not a scenario participant")
        events = session.violations.setdefault(player_id, [])
        if event_id not in events:
            events.append(event_id)

    def public_session(self, session_id: str) -> dict[str, Any]:
        session = self.sessions[session_id]
        return {
            "sessionId": session.id,
            "scenarioId": session.definition.id,
            "state": session.state.value,
            "participants": [
                {
                    "id": player_id,
                    "roleId": role_id,
                    "finished": player_id in session.finished_players,
                    "passed": not session.violations.get(player_id),
                    "violationIds": session.violations.get(player_id, []),
                    "xp": session.xp.get(player_id, 0),
                }
                for player_id, role_id in session.participants.items()
            ],
        }
