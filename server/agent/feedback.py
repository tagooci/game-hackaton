"""Local Ollama-backed feedback generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .parser import ScenarioResult


class FeedbackGenerationError(RuntimeError):
    """Raised when the configured local model cannot generate feedback."""


@dataclass(frozen=True)
class FeedbackConfig:
    """Generation settings loaded from environment variables."""

    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:3b"
    timeout_seconds: float = 30.0
    temperature: float = 0.8
    top_p: float = 0.9
    max_tokens: int = 400
    verbosity: str = "normal"
    tone: str = "friendly"

    @classmethod
    def from_environment(cls) -> "FeedbackConfig":
        return cls(
            base_url=os.getenv("OLLAMA_URL", cls.base_url).rstrip("/"),
            model=os.getenv("OLLAMA_MODEL", cls.model),
            timeout_seconds=_env_float("AGENT_TIMEOUT_SECONDS", cls.timeout_seconds, minimum=1),
            temperature=_env_float("AGENT_TEMPERATURE", cls.temperature, minimum=0, maximum=2),
            top_p=_env_float("AGENT_TOP_P", cls.top_p, minimum=0, maximum=1),
            max_tokens=_env_int("AGENT_MAX_TOKENS", cls.max_tokens, minimum=64, maximum=2048),
            verbosity=_env_choice(
                "AGENT_VERBOSITY",
                cls.verbosity,
                {"brief", "normal", "detailed"},
            ),
            tone=_env_choice(
                "AGENT_TONE",
                cls.tone,
                {"neutral", "friendly", "coach"},
            ),
        )


@dataclass(frozen=True)
class FeedbackError:
    violation_id: str
    comment: str


@dataclass(frozen=True)
class SuccessfulItem:
    category: str
    comment: str


@dataclass(frozen=True)
class ScenarioFeedback:
    successful: tuple[SuccessfulItem, ...]
    errors: tuple[FeedbackError, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "successful": [
                {"category": item.category, "comment": item.comment}
                for item in self.successful
            ],
            "errors": [
                {"violationId": item.violation_id, "comment": item.comment}
                for item in self.errors
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class OllamaFeedbackGenerator:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30,
        config: FeedbackConfig | None = None,
    ) -> None:
        loaded = config or FeedbackConfig.from_environment()
        self.base_url = (base_url or loaded.base_url).rstrip("/")
        self.model = model or loaded.model
        self.timeout_seconds = timeout_seconds if timeout_seconds != 30 else loaded.timeout_seconds
        self.temperature = loaded.temperature
        self.top_p = loaded.top_p
        self.max_tokens = loaded.max_tokens
        self.verbosity = loaded.verbosity
        self.tone = loaded.tone

    async def generate(self, result: ScenarioResult) -> ScenarioFeedback:
        prompt = _build_prompt(result, self.verbosity, self.tone)
        response_schema = _feedback_schema(result)
        raw_response = await asyncio.to_thread(
            self._generate_sync, prompt, self.temperature, response_schema
        )
        try:
            return parse_feedback(raw_response, result)
        except FeedbackGenerationError as first_error:
            repair_prompt = _build_repair_prompt(result, raw_response, first_error)
            repaired = await asyncio.to_thread(
                self._generate_sync, repair_prompt, min(self.temperature, 0.2), response_schema
            )
            return parse_feedback(repaired, result)

    def _generate_sync(
        self, prompt: str, temperature: float, response_schema: dict[str, object]
    ) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "format": response_schema,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "top_p": self.top_p,
                    "num_predict": self.max_tokens,
                },
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
        except HTTPError as exc:
            raise FeedbackGenerationError(
                f"Ollama returned HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise FeedbackGenerationError(
                f"cannot reach Ollama at {self.base_url}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise FeedbackGenerationError("Ollama returned invalid JSON") from exc

        text = body.get("response") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise FeedbackGenerationError("Ollama returned an empty response")
        return text.strip()


def _build_prompt(result: ScenarioResult, verbosity: str = "normal", tone: str = "friendly") -> str:
    facts = {
        "status": result.status.value,
        "scenario": result.scenario_id,
        "durationMs": result.duration_ms,
        "checks": {
            name.value: {
                "checked": check.checked,
                "violationCount": check.violation_count,
            }
            for name, check in result.checks.items()
        },
        "violations": [
            {
                "category": violation.category.value,
                "ruleId": violation.rule_id,
                "timeMs": violation.time_ms,
                "signId": violation.sign_id,
                "details": violation.details,
            }
            for violation in result.violations
        ],
    }
    return (
        "Ты создаёшь структурированную обратную связь по прохождению учебного участка ПДД.\n"
        "Используй только факты из JSON. Не придумывай нарушения и не меняй их количество.\n"
        "Не называй непроверенную категорию успешной. Не выставляй оценку и не говори "
        "«сдал» или «не сдал».\n"
        "Верни только JSON точно такого вида: "
        '{"successful":[{"category":"roadMarkings","comment":"фраза о выполненном элементе"}],'
        '"errors":[{"violationId":"id из violations","comment":"комментарий об ошибке"}]}.\n'
        "В successful добавь по одной короткой фразе для каждой проверенной категории "
        "с нулём нарушений. В errors добавь ровно по одному объекту для каждого нарушения, "
        "используя точное значение поля id, а не ruleId. "
        f"Объём текста: {verbosity}. Тон: {tone}. "
        "Пиши по-русски, естественно и каждый раз немного по-разному. "
        "Для brief используй короткие фразы, для detailed добавляй краткое пояснение "
        "причины ошибки, но не выдумывай факты.\n\n"
        f"Факты:\n{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )


def _env_float(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"{minimum}..{maximum}" if maximum is not None else f">={minimum}"
        raise ValueError(f"{name} must be {bound}")
    return value


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default)
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return value


def _feedback_schema(result: ScenarioResult) -> dict[str, object]:
    categories = [
        name.value
        for name, check in result.checks.items()
        if check.checked and check.violation_count == 0
    ]
    violation_ids = [violation.id for violation in result.violations]
    return {
        "type": "object",
        "properties": {
            "successful": {
                "type": "array",
                "minItems": len(categories),
                "maxItems": len(categories),
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": categories},
                        "comment": {"type": "string"},
                    },
                    "required": ["category", "comment"],
                },
            },
            "errors": {
                "type": "array",
                "minItems": len(violation_ids),
                "maxItems": len(violation_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "violationId": {"type": "string", "enum": violation_ids},
                        "comment": {"type": "string"},
                    },
                    "required": ["violationId", "comment"],
                },
            },
        },
        "required": ["successful", "errors"],
    }


def _build_repair_prompt(
    result: ScenarioResult, raw_response: str, error: FeedbackGenerationError
) -> str:
    expected_ids = [violation.id for violation in result.violations]
    expected_successes = [
        name.value
        for name, check in result.checks.items()
        if check.checked and check.violation_count == 0
    ]
    return (
        "Исправь JSON обратной связи. Верни только валидный JSON без markdown.\n"
        "Сохрани смысл комментариев, но используй только точные идентификаторы из списка.\n"
        f"Точные violationId: {json.dumps(expected_ids, ensure_ascii=False)}\n"
        f"Точные категории successful, все обязательны ровно по одному разу: "
        f"{json.dumps(expected_successes, ensure_ascii=False)}\n"
        f"Исходный ответ: {raw_response}\n"
        f"Причина отклонения: {error}\n"
        'Формат: {"successful":[{"category":"...","comment":"..."}],'
        '"errors":[{"violationId":"...","comment":"..."}]}'
    )


def parse_feedback(raw_response: str, result: ScenarioResult) -> ScenarioFeedback:
    try:
        value = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise FeedbackGenerationError("Ollama returned feedback that is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FeedbackGenerationError("feedback must be a JSON object")

    successful = value.get("successful")
    errors = value.get("errors")
    if not isinstance(successful, list):
        raise FeedbackGenerationError("feedback.successful must be an array")
    parsed_successful: list[SuccessfulItem] = []
    for item in successful:
        if not isinstance(item, dict):
            raise FeedbackGenerationError("feedback.successful items must be objects")
        category = item.get("category")
        comment = item.get("comment")
        if (
            not isinstance(category, str)
            or not isinstance(comment, str)
            or not category.strip()
            or not comment.strip()
        ):
            raise FeedbackGenerationError(
                "each successful item needs category and non-empty comment"
            )
        parsed_successful.append(SuccessfulItem(category.strip(), comment.strip()))
    if not isinstance(errors, list):
        raise FeedbackGenerationError("feedback.errors must be an array")

    expected_ids = [violation.id for violation in result.violations]
    parsed_errors: list[FeedbackError] = []
    for item in errors:
        if not isinstance(item, dict):
            raise FeedbackGenerationError("feedback.errors items must be objects")
        violation_id = item.get("violationId")
        comment = item.get("comment")
        if not isinstance(violation_id, str) or not isinstance(comment, str) or not comment.strip():
            raise FeedbackGenerationError("each error needs violationId and non-empty comment")
        parsed_errors.append(FeedbackError(violation_id, comment.strip()))

    actual_ids = [item.violation_id for item in parsed_errors]
    if actual_ids != expected_ids:
        raise FeedbackGenerationError(
            "feedback.errors must contain every violation exactly once and in input order"
        )
    expected_successful = {
        name.value
        for name, check in result.checks.items()
        if check.checked and check.violation_count == 0
    }
    actual_successful = [item.category for item in parsed_successful]
    if set(actual_successful) != expected_successful or len(actual_successful) != len(
        expected_successful
    ):
        raise FeedbackGenerationError(
            "feedback.successful must contain each checked zero-violation category exactly once"
        )
    return ScenarioFeedback(tuple(parsed_successful), tuple(parsed_errors))
