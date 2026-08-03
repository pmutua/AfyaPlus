"""Privacy-safe OpenRouter model access for SPEC-7.1."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from app.agent.prompts import SYSTEM_PROMPT
from app.safeguards.masking import mask

DEFAULT_MODELS = ("openai/gpt-4o-mini", "openai/gpt-4o")
EVALUATION_PROMPT_VERSION = "spec-7.1-v2"
_PLACEHOLDER_MARKERS = ("<your-", "replace-with", "sk-your")


class EvaluationConfigurationError(RuntimeError):
    """Raised when the standalone evaluation provider is misconfigured."""


@dataclass(frozen=True)
class EvaluationSettings:
    """Resolved OpenRouter settings, isolated from app/config.py."""

    api_key: str
    base_url: str
    models: tuple[str, ...]
    judge_model: str
    timeout_seconds: float


@dataclass(frozen=True)
class ModelResponse:
    """One generated answer plus provider usage evidence."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ModelResponse":
        return cls(
            text=str(payload["text"]),
            prompt_tokens=int(payload["prompt_tokens"]),
            completion_tokens=int(payload["completion_tokens"]),
            latency_ms=float(payload["latency_ms"]),
        )


ClientFactory = Callable[..., Any]


def _require_key() -> str:
    value = os.getenv("OPENROUTER_API_KEY", "")
    if not value or any(marker in value.lower() for marker in _PLACEHOLDER_MARKERS):
        raise EvaluationConfigurationError("A real OPENROUTER_API_KEY is required.")
    return value


def _models_from_env() -> tuple[str, ...]:
    raw = os.getenv("EVALUATION_MODELS", ",".join(DEFAULT_MODELS))
    models = tuple(model.strip() for model in raw.split(",") if model.strip())
    if not models:
        raise EvaluationConfigurationError("EVALUATION_MODELS cannot be empty.")
    return models


def _positive_timeout() -> float:
    try:
        timeout = float(os.getenv("EVALUATION_TIMEOUT_SECONDS", "60"))
    except ValueError as error:
        raise EvaluationConfigurationError(
            "EVALUATION_TIMEOUT_SECONDS must be numeric."
        ) from error
    if timeout <= 0:
        raise EvaluationConfigurationError(
            "EVALUATION_TIMEOUT_SECONDS must be positive."
        )
    return timeout


def load_settings() -> EvaluationSettings:
    """Load standalone evaluation settings and fail before any paid call."""

    load_dotenv()
    base_url = os.getenv(
        "EVALUATION_BASE_URL",
        "https://openrouter.ai/api/v1",
    )
    if not base_url.startswith(("http://", "https://")):
        raise EvaluationConfigurationError("EVALUATION_BASE_URL must be an http(s) URL.")
    return EvaluationSettings(
        api_key=_require_key(),
        base_url=base_url,
        models=_models_from_env(),
        judge_model=os.getenv("EVALUATION_JUDGE_MODEL", DEFAULT_MODELS[0]),
        timeout_seconds=_positive_timeout(),
    )


def build_client(
    settings: EvaluationSettings,
    client_factory: ClientFactory = OpenAI,
) -> Any:
    """Build one OpenAI-compatible OpenRouter client."""

    return client_factory(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout_seconds,
        max_retries=0,
    )


def _user_prompt(
    question: str,
    clinical_reference: str,
    source_file: str,
) -> str:
    masked_question = mask(question).masked_text
    masked_reference = mask(clinical_reference).masked_text
    return (
        "RETRIEVED AFYAPLUS KNOWLEDGE SOURCE:\n"
        f"[Source: {source_file}]\n{masked_reference}\n\n"
        f"USER QUESTION:\n{masked_question}\n\n"
        "Answer only from the retrieved source, preserve placeholders exactly, "
        "and cite the supplied source path with supported claims."
    )


def query_model(
    settings: EvaluationSettings,
    model: str,
    question: str,
    clinical_reference: str,
    source_file: str,
    client_factory: ClientFactory = OpenAI,
) -> ModelResponse:
    """Generate one masked, context-grounded comparison response."""

    client = build_client(settings, client_factory)
    started = perf_counter()
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=450,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _user_prompt(question, clinical_reference, source_file),
            },
        ],
    )
    usage = response.usage
    return ModelResponse(
        text=(response.choices[0].message.content or "").strip(),
        prompt_tokens=int(usage.prompt_tokens if usage else 0),
        completion_tokens=int(usage.completion_tokens if usage else 0),
        latency_ms=round((perf_counter() - started) * 1000, 2),
    )
