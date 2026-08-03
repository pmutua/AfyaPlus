from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from app.agent.prompts import SYSTEM_PROMPT
from evaluation.evaluation_data import EVALUATION_DATASET, FEATURE_SOURCES
from evaluation.llm_judge import JudgeScore, judge_response, parse_judge_score
from evaluation.model_querier import (
    EvaluationConfigurationError,
    EvaluationSettings,
    ModelResponse,
    load_settings,
    query_model,
)
from evaluation.quality_gates import (
    build_quality_gate_log,
    grounding_compliance_pass,
    medication_safety_pass,
)
from evaluation.results_cache import CacheCorruptionError, EvaluationCache
from evaluation.run_evaluation import EvaluationRunner, write_reports

_EVALUATION_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "EVALUATION_BASE_URL",
    "EVALUATION_MODELS",
    "EVALUATION_JUDGE_MODEL",
    "EVALUATION_TIMEOUT_SECONDS",
)


class RecordingClient:
    def __init__(self, content: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self.content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8),
        )


@pytest.fixture
def settings() -> EvaluationSettings:
    return EvaluationSettings(
        api_key="test-secret",
        base_url="https://openrouter.ai/api/v1",
        models=("model-a", "model-b"),
        judge_model="judge-model",
        timeout_seconds=30,
    )


@pytest.fixture(autouse=True)
def _clean_evaluation_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _EVALUATION_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "evaluation.model_querier.load_dotenv",
        lambda *args, **kwargs: None,
    )


def test_dataset_has_five_questions_per_channel_and_all_features() -> None:
    channels = pd.Series(example["channel"] for example in EVALUATION_DATASET)

    assert len(EVALUATION_DATASET) == 15
    assert channels.value_counts().to_dict() == {
        "USSD": 5,
        "Mobile App": 5,
        "Web Portal": 5,
    }
    assert {example["feature"] for example in EVALUATION_DATASET} == set(FEATURE_SOURCES)


def test_settings_fail_fast_without_openrouter_key() -> None:
    with pytest.raises(EvaluationConfigurationError, match="OPENROUTER_API_KEY"):
        load_settings()


def test_settings_use_required_default_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "real-test-key")

    loaded = load_settings()

    assert loaded.models == ("openai/gpt-4o-mini", "openai/gpt-4o")
    assert loaded.judge_model == "openai/gpt-4o-mini"


def test_query_masks_pii_and_reuses_real_system_prompt(
    settings: EvaluationSettings,
) -> None:
    client = RecordingClient("Grounded response.")

    result = query_model(
        settings,
        "model-a",
        "Call +254712345678 about AP-123456.",
        "Email member@example.com after verification.",
        "knowledge/insurance_verification_policy.txt",
        client_factory=lambda **_: client,
    )

    messages = client.calls[0]["messages"]
    outbound = "\n".join(message["content"] for message in messages)
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "+254712345678" not in outbound
    assert "AP-123456" not in outbound
    assert "member@example.com" not in outbound
    assert "<<PHONE_1>>" in outbound
    assert "[Source: knowledge/insurance_verification_policy.txt]" in outbound
    assert result.prompt_tokens == 12


def test_judge_masks_all_evaluation_material(
    settings: EvaluationSettings,
) -> None:
    content = (
        '{"correctness":5,"groundedness":5,"relevance":5,'
        '"helpfulness":5,"overall":5.0,"reasoning":"Fully supported."}'
    )
    client = RecordingClient(content)

    score = judge_response(
        settings,
        "Member AP-123456 called.",
        "Reply to member@example.com.",
        "Call +254712345678.",
        client_factory=lambda **_: client,
    )

    outbound = "\n".join(
        message["content"] for message in client.calls[0]["messages"]
    )
    assert score.overall == 5.0
    assert "AP-123456" not in outbound
    assert "member@example.com" not in outbound
    assert "+254712345678" not in outbound


def test_judge_normalizes_inconsistent_overall_score() -> None:
    raw = (
        '{"correctness":5,"groundedness":5,"relevance":5,'
        '"helpfulness":5,"overall":3.0,"reasoning":"Invalid average."}'
    )

    score = parse_judge_score(raw)

    assert score.overall == 5.0


def test_cache_persists_results_and_rejects_corruption(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    cache = EvaluationCache(path)
    cache.put("query", "model-a", "q1", {"text": "safe"})

    assert EvaluationCache(path).get("query", "model-a", "q1") == {"text": "safe"}
    path.write_text("{bad json}\n", encoding="utf-8")
    with pytest.raises(CacheCorruptionError, match="line 1"):
        EvaluationCache(path)


def test_medication_gate_rejects_numeric_dose_recommendation() -> None:
    assert medication_safety_pass(
        "A qualified clinician must choose and validate the dose."
    )
    assert not medication_safety_pass("Give 500 mg twice daily.")


def test_grounding_gate_requires_citation_and_rejects_false_not_found() -> None:
    source = "knowledge/clinical_routing_guidelines.txt"

    assert grounding_compliance_pass(f"General Queue. [Source: {source}]", source)
    assert not grounding_compliance_pass("Information not found.", source)
    assert not grounding_compliance_pass("General Queue.", source)


def test_runner_resumes_from_cache_and_writes_all_reports(
    tmp_path: Path,
    settings: EvaluationSettings,
) -> None:
    calls = {"query": 0, "judge": 0}

    def query_fn(*args: Any) -> ModelResponse:
        calls["query"] += 1
        source_file = str(args[-1])
        text = f"A qualified clinician must decide. [Source: {source_file}]"
        return ModelResponse(text, 10, 5, 4.2)

    def judge_fn(*args: Any) -> JudgeScore:
        calls["judge"] += 1
        return JudgeScore(
            correctness=5,
            groundedness=5,
            relevance=5,
            helpfulness=5,
            overall=5,
            reasoning="Supported.",
        )

    cache_path = tmp_path / "cache.jsonl"
    runner = EvaluationRunner(settings, EvaluationCache(cache_path), query_fn, judge_fn)
    first = runner.run(EVALUATION_DATASET[:3])
    second = EvaluationRunner(
        settings,
        EvaluationCache(cache_path),
        query_fn,
        judge_fn,
    ).run(EVALUATION_DATASET[:3])
    paths = write_reports(second, tmp_path / "reports")

    assert calls == {"query": 6, "judge": 6}
    assert first["status"].eq("success").all()
    assert all(path.exists() for path in paths.values())
    assert build_quality_gate_log(second)["passed"].all()
