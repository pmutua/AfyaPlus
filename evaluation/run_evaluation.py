"""Resilient SPEC-7.1 batch runner and report writer."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

from evaluation.evaluation_data import (
    EVALUATION_DATASET,
    FEATURE_SOURCES,
    EvaluationExample,
)
from evaluation.evaluator import evaluate_response
from evaluation.llm_judge import JUDGE_PROMPT_VERSION, JudgeScore, judge_response
from evaluation.model_querier import (
    EvaluationSettings,
    EVALUATION_PROMPT_VERSION,
    ModelResponse,
    load_settings,
    query_model,
)
from evaluation.quality_gates import (
    build_quality_gate_log,
    grounding_compliance_pass,
    medication_safety_pass,
)
from evaluation.results_cache import EvaluationCache

QueryFunction = Callable[
    [EvaluationSettings, str, str, str, str],
    ModelResponse,
]
JudgeFunction = Callable[
    [EvaluationSettings, str, str, str],
    JudgeScore,
]

REPORT_FILENAMES = {
    "full": "full_evaluation_results.csv",
    "judge": "llm_judge_matrix.csv",
    "summary": "model_comparison_summary.csv",
    "gates": "quality_gate_log.csv",
}


class EvaluationRunner:
    """Run every model/question independently so one failure cannot abort a batch."""

    def __init__(
        self,
        settings: EvaluationSettings,
        cache: EvaluationCache,
        query_fn: QueryFunction = query_model,
        judge_fn: JudgeFunction = judge_response,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.query_fn = query_fn
        self.judge_fn = judge_fn

    def _query(self, model: str, example: EvaluationExample) -> ModelResponse:
        stage = f"query:{EVALUATION_PROMPT_VERSION}"
        cached = self.cache.get(stage, model, example["id"])
        if cached is not None:
            return ModelResponse.from_dict(cached)
        response = self.query_fn(
            self.settings,
            model,
            example["question"],
            example["clinical_reference"],
            FEATURE_SOURCES[example["feature"]],
        )
        self.cache.put(stage, model, example["id"], response.to_dict())
        return response

    def _judge(
        self,
        model: str,
        example: EvaluationExample,
        response: ModelResponse,
    ) -> JudgeScore:
        stage = f"judge:{JUDGE_PROMPT_VERSION}:{self.settings.judge_model}"
        cached = self.cache.get(stage, model, example["id"])
        if cached is not None:
            return JudgeScore.model_validate(cached)
        score = self.judge_fn(
            self.settings,
            example["question"],
            example["clinical_reference"],
            response.text,
        )
        self.cache.put(stage, model, example["id"], score.model_dump())
        return score

    def _base_row(
        self,
        model: str,
        example: EvaluationExample,
    ) -> dict[str, object]:
        return {
            "question_id": example["id"],
            "channel": example["channel"],
            "feature": example["feature"],
            "source_file": FEATURE_SOURCES[example["feature"]],
            "model": model,
            "prompt_version": EVALUATION_PROMPT_VERSION,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
        }

    def _success_row(
        self,
        model: str,
        example: EvaluationExample,
        response: ModelResponse,
        score: JudgeScore,
    ) -> dict[str, object]:
        return {
            **self._base_row(model, example),
            "status": "success",
            "hypothesis": response.text,
            **evaluate_response(example["clinical_reference"], response.text),
            **score.model_dump(),
            "grounding_compliance_pass": grounding_compliance_pass(
                response.text,
                FEATURE_SOURCES[example["feature"]],
            ),
            "medication_safety_pass": (
                medication_safety_pass(response.text)
                if example["feature"] == "medication_safety"
                else True
            ),
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "latency_ms": response.latency_ms,
            "error_stage": "",
            "error_type": "",
            "error_message": "",
        }

    def _failure_row(
        self,
        model: str,
        example: EvaluationExample,
        stage: str,
        error: Exception,
        response: ModelResponse | None = None,
    ) -> dict[str, object]:
        message = str(error).replace(self.settings.api_key, "[REDACTED]")[:300]
        return {
            **self._base_row(model, example),
            "status": "failed",
            "hypothesis": response.text if response else "",
            "grounding_compliance_pass": False,
            "medication_safety_pass": False,
            "prompt_tokens": response.prompt_tokens if response else 0,
            "completion_tokens": response.completion_tokens if response else 0,
            "latency_ms": response.latency_ms if response else 0,
            "error_stage": stage,
            "error_type": type(error).__name__,
            "error_message": message,
        }

    def _evaluate_one(
        self,
        model: str,
        example: EvaluationExample,
    ) -> dict[str, object]:
        try:
            response = self._query(model, example)
        except Exception as error:
            return self._failure_row(model, example, "query", error)
        try:
            score = self._judge(model, example, response)
        except Exception as error:
            return self._failure_row(model, example, "judge", error, response)
        return self._success_row(model, example, response, score)

    def run(
        self,
        dataset: Sequence[EvaluationExample] = EVALUATION_DATASET,
    ) -> pd.DataFrame:
        """Return all model/question results, including visible failures."""

        rows = [
            self._evaluate_one(model, example)
            for example in dataset
            for model in self.settings.models
        ]
        return pd.DataFrame(rows)


def _successful_summary(results: pd.DataFrame) -> pd.DataFrame:
    successful = results[results["status"] == "success"]
    columns = [
        "bleu_4",
        "rouge_l",
        "token_f1",
        "correctness",
        "groundedness",
        "relevance",
        "helpfulness",
        "overall",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
    ]
    if successful.empty:
        return pd.DataFrame(columns=["model", *columns])
    return successful.groupby("model")[columns].mean().round(4).reset_index()


def build_model_summary(
    results: pd.DataFrame,
    gate_log: pd.DataFrame,
) -> pd.DataFrame:
    """Combine quality means, success counts, and final eligibility."""

    counts = (
        results.assign(success=results["status"].eq("success"))
        .groupby("model")
        .agg(total_questions=("question_id", "count"), successful_questions=("success", "sum"))
        .reset_index()
    )
    counts["failed_questions"] = (
        counts["total_questions"] - counts["successful_questions"]
    )
    gate_status = gate_log.groupby("model")["passed"].all().rename("all_gates_passed")
    return counts.merge(_successful_summary(results), on="model", how="left").merge(
        gate_status,
        on="model",
        how="left",
    )


def write_reports(results: pd.DataFrame, output_dir: Path) -> dict[str, Path]:
    """Write the four rubric-required CSV artifacts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    gate_log = build_quality_gate_log(results)
    judge_columns = [
        "question_id",
        "channel",
        "feature",
        "model",
        "status",
        "correctness",
        "groundedness",
        "relevance",
        "helpfulness",
        "overall",
        "reasoning",
    ]
    paths = {name: output_dir / filename for name, filename in REPORT_FILENAMES.items()}
    results.to_csv(paths["full"], index=False)
    results.reindex(columns=judge_columns).to_csv(paths["judge"], index=False)
    build_model_summary(results, gate_log).to_csv(paths["summary"], index=False)
    gate_log.to_csv(paths["gates"], index=False)
    return paths


def run_pipeline(
    output_dir: Path = Path("evaluation"),
    cache_path: Path = Path("evaluation/.cache/results.jsonl"),
) -> dict[str, Path]:
    """Resolve settings, run the comparison, and persist evidence."""

    settings = load_settings()
    runner = EvaluationRunner(settings, EvaluationCache(cache_path))
    return write_reports(runner.run(), output_dir)


def main() -> None:
    """Run the paid comparison only when invoked explicitly."""

    for name, path in run_pipeline().items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
