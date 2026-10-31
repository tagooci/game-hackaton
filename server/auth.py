from __future__ import annotations

import hashlib
import hmac
import secrets

from .db import Database

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 32
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_NAME_LENGTH = 24


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


class AuthService:
    """Authentication policy; persistence remains encapsulated in Database."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_account(
        self, username: str, password: str, name: str | None = None
    ) -> str:
        username = username.strip()
        account_name = (name or username).strip()
        if not MIN_USERNAME_LENGTH <= len(username) <= MAX_USERNAME_LENGTH:
            raise ValueError("username must be 3-32 characters")
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise ValueError("password must be 8-128 characters")
        if not 1 <= len(account_name) <= MAX_NAME_LENGTH:
            raise ValueError("name must be 1-24 characters")
        return self.database.create_account(
            username, hash_password(password), account_name
        )

    def authenticate(self, username: str, password: str) -> dict | None:
        account = self.database.account_for_credentials(username)
        if account is None or not verify_password(password, account["passwordHash"]):
            return None
        return {"playerId": account["playerId"], "name": account["name"]}

    def create_session(self, player_id: str) -> str:
        return self.database.create_session(player_id)

    def account_for_session(self, token: str | None) -> dict | None:
        return self.database.account_for_session(token)

    def delete_session(self, token: str | None) -> str | None:
        return self.database.delete_session(token)
