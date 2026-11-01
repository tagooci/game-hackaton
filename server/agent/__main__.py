"""Run the feedback agent against a completed result JSON.

Usage:
    python -m server.agent result.json
    cat result.json | python -m server.agent -
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ..db import Database
from .feedback import FeedbackGenerationError
from .parser import ResultParseError
from .service import AgentService


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate feedback for a completed scenario result."
    )
    parser.add_argument(
        "input",
        help="Path to the result JSON, or '-' to read JSON from stdin.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite database path (defaults to GAME_DB_PATH or db/game.sqlite3).",
    )
    return parser.parse_args()


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


async def _run() -> int:
    arguments = _arguments()
    database = Database(arguments.db)
    database.initialize()
    try:
        ingested, feedback = await AgentService(database).ingest_and_generate(
            _read_input(arguments.input)
        )
    except (OSError, UnicodeError, ResultParseError, FeedbackGenerationError) as error:
        print(f"agent input error: {error}", file=sys.stderr)
        return 2
    finally:
        database.close()

    print(
        json.dumps(
            {
                "resultId": ingested.result.result_id,
                "isNew": ingested.is_new,
                "feedback": feedback.to_dict(),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
