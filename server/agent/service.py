"""Application service for ingesting scenario results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..db import Database
from .feedback import OllamaFeedbackGenerator, ScenarioFeedback, parse_feedback
from .parser import ScenarioResult, parse_result, parse_result_json


@dataclass(frozen=True)
class IngestedResult:
    """Outcome of accepting a scenario result."""

    result: ScenarioResult
    is_new: bool


class AgentService:
    """Coordinates input validation and durable storage for agent results."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def ingest_json(self, payload: str | bytes) -> IngestedResult:
        return self.ingest(parse_result_json(payload))

    def ingest_object(self, payload: Any) -> IngestedResult:
        return self.ingest(parse_result(payload))

    def ingest(self, result: ScenarioResult) -> IngestedResult:
        is_new = self.database.save_agent_result(result)
        return IngestedResult(result=result, is_new=is_new)

    async def ingest_and_generate(
        self, payload: str | bytes
    ) -> tuple[IngestedResult, ScenarioFeedback]:
        ingested = self.ingest_json(payload)
        if not ingested.is_new:
            existing_feedback = self.database.agent_feedback(ingested.result.result_id)
            if existing_feedback is not None:
                return ingested, parse_feedback(existing_feedback, ingested.result)
        generator = OllamaFeedbackGenerator()
        feedback = await generator.generate(ingested.result)
        self.database.save_agent_feedback(
            result_id=ingested.result.result_id,
            player_id=ingested.result.player_id,
            text=feedback.to_json(),
            model=generator.model,
        )
        return ingested, feedback
