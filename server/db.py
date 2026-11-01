from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent.parser import ScenarioResult


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent / "db" / "game.sqlite3"
)


def level_for_experience(experience: int) -> int:
    if experience < 800:
        return 1
    if experience < 1500:
        return 2
    return 3


class Database:
    """SQLite repository. Only this module knows the schema and SQL queries."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured_path = path or os.getenv("GAME_DB_PATH")
        self.path = Path(configured_path) if configured_path else DEFAULT_DB_PATH
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS accounts (
                    player_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    experience INTEGER NOT NULL DEFAULT 0,
                    vehicle_color INTEGER NOT NULL DEFAULT 3,
                    vehicle_type TEXT NOT NULL DEFAULT 'car',
                    safe_x REAL NOT NULL DEFAULT 0,
                    safe_z REAL NOT NULL DEFAULT 0,
                    safe_heading REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    player_id TEXT NOT NULL REFERENCES accounts(player_id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

        with self._connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(accounts)")}
            for name, definition in [
                ("experience", "INTEGER NOT NULL DEFAULT 0"),
                ("safe_y", "REAL NOT NULL DEFAULT 0"),
                ("safe_world", "TEXT NOT NULL DEFAULT ''"),
                ("vehicle_color", "INTEGER NOT NULL DEFAULT 3"),
                ("vehicle_type", "TEXT NOT NULL DEFAULT 'car'"),
            ]:
                if name not in columns:
                    db.execute(f"ALTER TABLE accounts ADD COLUMN {name} {definition}")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS scenario_results (
                    result_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    player_id TEXT NOT NULL REFERENCES accounts(player_id),
                    role_id TEXT NOT NULL,
                    passed INTEGER,
                    experience INTEGER NOT NULL,
                    violation_ids TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (result_id, player_id)
                );
                CREATE TABLE IF NOT EXISTS agent_results (
                    result_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    scenario_version INTEGER NOT NULL,
                    scenario_type TEXT NOT NULL,
                    player_id TEXT NOT NULL REFERENCES accounts(player_id),
                    role_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    checks_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS agent_violations (
                    violation_id TEXT NOT NULL,
                    result_id TEXT NOT NULL REFERENCES agent_results(result_id),
                    category TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    time_ms INTEGER NOT NULL,
                    position_json TEXT,
                    related_player_ids_json TEXT NOT NULL,
                    sign_id TEXT,
                    details TEXT NOT NULL,
                    PRIMARY KEY (result_id, violation_id)
                );
                CREATE TABLE IF NOT EXISTS agent_feedback (
                    result_id TEXT PRIMARY KEY REFERENCES agent_results(result_id),
                    player_id TEXT NOT NULL REFERENCES accounts(player_id),
                    feedback TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def safe_context(self, player_id: str) -> tuple[str, float]:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT safe_world, safe_y FROM accounts WHERE player_id = ?", (player_id,)).fetchone()
        return (row['safe_world'], row['safe_y']) if row else ('', 0)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def create_account(
        self, username: str, password_hash: str, name: str | None = None
    ) -> str:
        username = username.strip()
        account_name = (name or username).strip()
        if not username or not password_hash or not account_name:
            raise ValueError("username, password_hash and name are required")

        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT player_id FROM accounts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            next_number = int(row["player_id"][1:]) + 1 if row else 1
            player_id = f"p{next_number}"
            db.execute(
                """
                INSERT INTO accounts
                    (player_id, username, name, password_hash)
                VALUES (?, ?, ?, ?)
                """,
                (player_id, username, account_name, password_hash),
            )
        return player_id

    def account_for_credentials(self, username: str) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT player_id, name, password_hash
                FROM accounts WHERE username = ?
                """,
                (username.strip(),),
            ).fetchone()
        if row is None:
            return None
        return {
            "playerId": row["player_id"],
            "name": row["name"],
            "passwordHash": row["password_hash"],
        }

    def create_session(self, player_id: str) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO sessions (token_hash, player_id) VALUES (?, ?)",
                (token_hash, player_id),
            )
        return token

    def account_for_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT a.player_id, a.username, a.name
                    , a.experience, a.vehicle_color, a.vehicle_type
                FROM sessions s JOIN accounts a ON a.player_id = s.player_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        return {
            "playerId": row["player_id"],
            "username": row["username"],
            "name": row["name"],
            "experience": int(row["experience"]),
            "vehicleColor": int(row["vehicle_color"]),
            "vehicleType": row["vehicle_type"],
        }

    def profile(self, player_id: str) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT experience, vehicle_color, vehicle_type FROM accounts WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        if row is None:
            return None
        experience = int(row["experience"])
        return {
            "experience": experience,
            "level": level_for_experience(experience),
            "vehicleColor": int(row["vehicle_color"]),
            "vehicleType": row["vehicle_type"],
        }

    def update_profile(self, player_id: str, vehicle_color: int, vehicle_type: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE accounts SET vehicle_color = ?, vehicle_type = ? WHERE player_id = ?",
                (vehicle_color, vehicle_type, player_id),
            )

    def delete_session(self, token: str | None) -> str | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT player_id FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        return row["player_id"] if row is not None else None

    def safe_position(self, player_id: str) -> tuple[float, float, float]:
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT safe_x, safe_z, safe_heading
                FROM accounts WHERE player_id = ?
                """,
                (player_id,),
            ).fetchone()
        return (row["safe_x"], row["safe_z"], row["safe_heading"]) if row else (0, 0, 0)

    def save_safe_position(
        self, player_id: str, x: float, z: float, heading: float, y: float = 0, world: str = ""
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE accounts
                SET safe_x = ?, safe_z = ?, safe_heading = ?, safe_y = ?, safe_world = ?
                WHERE player_id = ?
                """,
                (x, z, heading, y, world, player_id),
            )

    def save_scenario_result(
        self,
        result_id: str,
        session_id: str,
        scenario_id: str,
        player_id: str,
        role_id: str,
        passed: bool,
        experience: int,
        violation_ids: list[str],
    ) -> bool:
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO scenario_results
                    (result_id, session_id, scenario_id, player_id, role_id,
                     passed, experience, violation_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    session_id,
                    scenario_id,
                    player_id,
                    role_id,
                    int(passed),
                    experience,
                    ",".join(violation_ids),
                ),
            )
            if cursor.rowcount == 0:
                return False
            db.execute(
                "UPDATE accounts SET experience = experience + ? WHERE player_id = ?",
                (experience, player_id),
            )
            return True

    def experience(self, player_id: str) -> int:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT experience FROM accounts WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        return int(row["experience"]) if row else 0

    def save_agent_result(self, result: "ScenarioResult") -> bool:
        """Persist a parsed result once, including all of its violations."""
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO agent_results
                    (result_id, session_id, scenario_id, scenario_version,
                     scenario_type, player_id, role_id, status, duration_ms,
                     checks_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.result_id,
                    result.session_id,
                    result.scenario_id,
                    result.scenario_version,
                    result.scenario_type.value,
                    result.player_id,
                    result.role_id,
                    result.status.value,
                    result.duration_ms,
                    json.dumps(
                        {
                            name.value: {
                                "checked": check.checked,
                                "violationCount": check.violation_count,
                            }
                            for name, check in result.checks.items()
                        },
                        separators=(",", ":"),
                    ),
                ),
            )
            if cursor.rowcount == 0:
                return False

            for violation in result.violations:
                db.execute(
                    """
                    INSERT INTO agent_violations
                        (violation_id, result_id, category, rule_id, time_ms,
                         position_json, related_player_ids_json, sign_id, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        violation.id,
                        result.result_id,
                        violation.category.value,
                        violation.rule_id,
                        violation.time_ms,
                        json.dumps(
                            {
                                "x": violation.position.x,
                                "y": violation.position.y,
                                "z": violation.position.z,
                            },
                            separators=(",", ":"),
                        )
                        if violation.position
                        else None,
                        json.dumps(list(violation.related_player_ids), separators=(",", ":")),
                        violation.sign_id,
                        violation.details,
                    ),
                )
            return True

    def save_agent_feedback(
        self, result_id: str, player_id: str, text: str, model: str
    ) -> bool:
        if not text.strip():
            raise ValueError("feedback text must not be empty")
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO agent_feedback
                    (result_id, player_id, feedback, model)
                VALUES (?, ?, ?, ?)
                """,
                (result_id, player_id, text, model),
            )
            return cursor.rowcount > 0

    def agent_feedback(self, result_id: str) -> str | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT feedback FROM agent_feedback WHERE result_id = ?",
                (result_id,),
            ).fetchone()
        return str(row["feedback"]) if row else None

    def close(self) -> None:
        """Connections are short-lived; kept as an explicit lifecycle hook."""
