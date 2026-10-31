from __future__ import annotations

import argparse
import getpass

from .auth import AuthService
from .db import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage local game accounts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create an account")
    create.add_argument("username")
    create.add_argument("--name")
    args = parser.parse_args()

    if args.command == "create":
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Repeat password: ")
        if password != confirmation:
            parser.error("passwords do not match")
        database = Database()
        database.initialize()
        player_id = AuthService(database).create_account(
            args.username, password, args.name
        )
        print(f"Created {args.username} ({player_id})")


if __name__ == "__main__":
    main()
