"""Append-only cache that prevents repeated paid evaluation calls."""

from __future__ import annotations

import json
from pathlib import Path


class CacheCorruptionError(RuntimeError):
    """Raised instead of silently discarding paid-call cache evidence."""


class EvaluationCache:
    """Store the latest payload for each model/question/stage key."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: dict[tuple[str, str, str], dict[str, object]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                key = self._key(record["stage"], record["model"], record["question_id"])
                self._records[key] = dict(record["payload"])
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise CacheCorruptionError(
                    f"Invalid evaluation cache record at line {line_number}."
                ) from error

    @staticmethod
    def _key(stage: str, model: str, question_id: str) -> tuple[str, str, str]:
        return stage, model, question_id

    def get(
        self,
        stage: str,
        model: str,
        question_id: str,
    ) -> dict[str, object] | None:
        """Return a defensive copy of a cached payload."""

        payload = self._records.get(self._key(stage, model, question_id))
        return dict(payload) if payload is not None else None

    def put(
        self,
        stage: str,
        model: str,
        question_id: str,
        payload: dict[str, object],
    ) -> None:
        """Append and flush one successful paid-call result immediately."""

        record = {
            "stage": stage,
            "model": model,
            "question_id": question_id,
            "payload": payload,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
        self._records[self._key(stage, model, question_id)] = dict(payload)
