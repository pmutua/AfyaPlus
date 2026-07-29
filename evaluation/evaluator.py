"""Deterministic lexical metrics for AfyaPlus model responses."""

from __future__ import annotations

import re
from collections import Counter

from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
from rouge_score import rouge_scorer


def tokenize(text: str) -> list[str]:
    """Normalize text into lowercase word tokens."""

    return re.findall(r"\b\w+\b", text.lower())


def bleu_score(reference: str, hypothesis: str) -> float:
    """Return smoothed sentence BLEU-4."""

    reference_tokens = tokenize(reference)
    hypothesis_tokens = tokenize(hypothesis)
    if not reference_tokens or not hypothesis_tokens:
        return float(reference_tokens == hypothesis_tokens)
    return float(
        sentence_bleu(
            [reference_tokens],
            hypothesis_tokens,
            weights=(0.25, 0.25, 0.25, 0.25),
            smoothing_function=SmoothingFunction().method1,
        )
    )


def rouge_scores(reference: str, hypothesis: str) -> dict[str, float]:
    """Return ROUGE-1, ROUGE-2 and ROUGE-L F1 values."""

    scorer = rouge_scorer.RougeScorer(
        ["rouge1", "rouge2", "rougeL"],
        use_stemmer=True,
    )
    scores = scorer.score(reference, hypothesis)
    return {name: value.fmeasure for name, value in scores.items()}


def token_f1(reference: str, hypothesis: str) -> float:
    """Return duplicate-aware token F1."""

    reference_tokens = tokenize(reference)
    hypothesis_tokens = tokenize(hypothesis)
    if not reference_tokens or not hypothesis_tokens:
        return float(reference_tokens == hypothesis_tokens)
    overlap = sum((Counter(reference_tokens) & Counter(hypothesis_tokens)).values())
    if not overlap:
        return 0.0
    precision = overlap / len(hypothesis_tokens)
    recall = overlap / len(reference_tokens)
    return 2 * precision * recall / (precision + recall)


def evaluate_response(reference: str, hypothesis: str) -> dict[str, float]:
    """Return the stable lexical report columns."""

    rouge = rouge_scores(reference, hypothesis)
    return {
        "bleu_4": round(bleu_score(reference, hypothesis), 4),
        "rouge_1": round(rouge["rouge1"], 4),
        "rouge_2": round(rouge["rouge2"], 4),
        "rouge_l": round(rouge["rougeL"], 4),
        "token_f1": round(token_f1(reference, hypothesis), 4),
    }
