from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent / "db" / "game.sqlite3"
)


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
            for name, definition in [("safe_y", "REAL NOT NULL DEFAULT 0"), ("safe_world", "TEXT NOT NULL DEFAULT ''")]:
                if name not in columns:
                    db.execute(f"ALTER TABLE accounts ADD COLUMN {name} {definition}")

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
                SELECT a.player_id, a.name
                FROM sessions s JOIN accounts a ON a.player_id = s.player_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        return {"playerId": row["player_id"], "name": row["name"]}

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

    def close(self) -> None:
        """Connections are short-lived; kept as an explicit lifecycle hook."""
