"""Server-side state machine for multiplayer driving scenarios.

The registry is intentionally data-driven. Map-specific zones and role spawns
are added after the next map import; the lifecycle does not depend on Blender.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import count
import math
from typing import Any


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
    destination: ScenarioZone | None = None


@dataclass(frozen=True)
class ScenarioDefinition:
    id: str
    map_id: str
    zone: ScenarioZone
    roles: tuple[ScenarioRole, ...]
    time_limit_seconds: float = 60.0

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


class ScenarioManager:
    def __init__(self, definitions: tuple[ScenarioDefinition, ...] = ()):
        self.definitions = {definition.id: definition for definition in definitions}
        self.candidates: dict[str, list[Candidate]] = {}
        self.sessions: dict[str, ScenarioSession] = {}
        self.player_sessions: dict[str, str] = {}
        self._session_ids = count(1)

    def register(self, definition: ScenarioDefinition) -> None:
        if definition.id in self.definitions:
            raise ValueError(f"duplicate scenario: {definition.id}")
        if len(definition.roles) < 2:
            raise ValueError("a scenario needs at least two roles")
        if len(definition.roles) > 3:
            raise ValueError("a scenario supports at most three roles")
        if not math.isfinite(definition.time_limit_seconds) or definition.time_limit_seconds <= 0:
            raise ValueError("time limit must be positive and finite")
        self.definitions[definition.id] = definition

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
        session = self.sessions[session_id]
        session.state = ScenarioState.CANCELLED
        for participant_id in session.participants:
            self.player_sessions.pop(participant_id, None)
        return [ScenarioEvent(
            "scenario_cancelled", session.definition.id, session.id,
            reason=reason,
        )]

    def set_state(self, session_id: str, state: ScenarioState, now: float | None = None) -> None:
        session = self.sessions[session_id]
        if state == ScenarioState.RUNNING:
            session.started_at = now
        session.state = state

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
        role_id = session.participants[player_id]
        role = next(role for role in session.definition.roles if role.id == role_id)
        if role.destination is None or not role.destination.contains(x, z, speed):
            return []

        session.finished_players.add(player_id)
        violations = tuple(session.violations.get(player_id, ()))
        events = [ScenarioEvent(
            "scenario_player_finished",
            session.definition.id,
            session.id,
            player_id,
            role_id=role_id,
            passed=not violations,
            violation_ids=violations,
        )]
        if len(session.finished_players) == len(session.participants):
            session.state = ScenarioState.FINISHED
            events.append(ScenarioEvent(
                "scenario_result",
                session.definition.id,
                session.id,
                reason="all_players_finished",
            ))
        return events

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
                }
                for player_id, role_id in session.participants.items()
            ],
        }
