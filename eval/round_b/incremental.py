"""Crash-safe local persistence for a logical Round B run."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


class IncompleteRequestError(RuntimeError): pass


class IncrementalStore:
    def __init__(self, directory: Path, run_id: str):
        self.directory, self.run_id = directory, run_id
        directory.mkdir(parents=True, exist_ok=True)
        self.events_path, self.turns_path, self.checkpoint_path = directory / "events.jsonl", directory / "turns.jsonl", directory / "checkpoint.json"

    def _append(self, path: Path, value: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"); f.flush(); os.fsync(f.fileno())

    def checkpoint(self) -> dict[str, dict[str, str]]:
        return json.loads(self.checkpoint_path.read_text(encoding="utf-8")) if self.checkpoint_path.exists() else {}

    def set_state(self, candidate_id: str, case_id: str, state: str) -> None:
        if state not in {"pending", "running", "completed", "aborted"}: raise ValueError(state)
        data = self.checkpoint(); data.setdefault(candidate_id, {})[case_id] = state
        tmp = self.checkpoint_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f: json.dump(data, f, sort_keys=True); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, self.checkpoint_path)

    def event(self, event_type: str, candidate_id: str, case_id: str, turn_index: int, model_round: int, attempt_index: int, **extra: Any) -> dict[str, Any]:
        value = {"event_id": uuid.uuid4().hex, "event_type": event_type, "run_id": self.run_id, "candidate_id": candidate_id, "case_id": case_id, "turn_index": turn_index, "model_round": model_round, "attempt_index": attempt_index, **extra}
        self._append(self.events_path, value); return value

    def turn(self, record: dict[str, Any]) -> None:
        forbidden = ("reasoning", "thought", "api_key", "authorization", "auth_header")
        clean = {k: v for k, v in record.items() if not any(word in k.lower() for word in forbidden)}
        self._append(self.turns_path, {"run_id": self.run_id, **clean})

    def reconcile(self, candidate_id: str, case_id: str) -> None:
        events = [json.loads(line) for line in self.events_path.read_text(encoding="utf-8").splitlines()] if self.events_path.exists() else []
        started = {e["event_id"] for e in events if e["event_type"] == "provider_request_started" and e["candidate_id"] == candidate_id and e["case_id"] == case_id}
        outcomes = {e.get("request_event_id") for e in events if e["event_type"] in {"provider_response_received", "provider_request_failed"}}
        if started - outcomes:
            self.event("request_outcome_unknown_due_process_termination", candidate_id, case_id, -1, -1, -1)
            self.set_state(candidate_id, case_id, "aborted")
            raise IncompleteRequestError(case_id)

    def begin_case(self, candidate_id: str, case_id: str) -> None:
        self.reconcile(candidate_id, case_id)
        state = self.checkpoint().get(candidate_id, {}).get(case_id, "pending")
        if state != "pending": raise RuntimeError(f"case is {state}")
        self.set_state(candidate_id, case_id, "running")

    def complete_case(self, candidate_id: str, case_id: str) -> None:
        if self.checkpoint().get(candidate_id, {}).get(case_id) != "running": raise RuntimeError("case is not running")
        self.set_state(candidate_id, case_id, "completed")
