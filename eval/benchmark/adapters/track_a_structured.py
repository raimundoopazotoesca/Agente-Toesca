"""Track A: the current structured architecture (`tools.db_chat.answer`),
wrapped behind the neutral adapter contract.

This module never modifies `tools/db_chat.py` or anything else in
`tools/`. It only points that module at the pinned snapshot for the
duration of each call and translates its return dict into a `Turn`.

Deliberately not read for scoring: `result["clarify"]`, `result["sql"]`,
`state["last_metric"]`, `state["last_entities"]`. Those are Track A
internals; using them here would give this track an advantage a
frontier-simple track (Track B) doesn't have. The grader infers
`asked_clarification` from `text` alone, same as it would for any track.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from eval.benchmark.adapters._sqlite_guard import guarded_sqlite
from eval.benchmark.adapters.base import Artifact, Turn, Usage
from eval.benchmark.snapshot import SnapshotSandbox

_CHART_BLOCK = re.compile(r"```chart\s*\n(.*?)```", re.DOTALL)


def _extract_artifacts(answer_md: str) -> list[Artifact]:
    artifacts = []
    for match in _CHART_BLOCK.finditer(answer_md or ""):
        artifacts.append(Artifact(kind="chart", payload=match.group(1).strip()))
    return artifacts


@dataclass
class _TrackASession:
    sandbox: SnapshotSandbox
    session_id: str
    history: list[dict]

    def ask(self, message: str) -> Turn:
        from tools import db_chat  # imported inside the guarded block's
        # caller, not at module load time, so importing this adapter never
        # touches the productive DB path before a sandbox is in scope.

        self.sandbox.log.reset()
        started = time.monotonic()
        with guarded_sqlite(self.sandbox):
            result = db_chat.answer(message, self.history, session_id=self.session_id)
        elapsed_ms = (time.monotonic() - started) * 1000

        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": result.get("answer_md", "")})

        return Turn(
            text=result.get("answer_md", ""),
            artifacts=_extract_artifacts(result.get("answer_md", "")),
            tool_calls=[],  # db_chat.answer doesn't instrument tool use today;
            # tool_requirements checks against this track are marked
            # `unscored`, not `fail` -- see adapters/base.py.
            usage=Usage(
                provider=result.get("provider"),
                model=result.get("provider"),
                calls=1,
                latency_ms=elapsed_ms,
            ),
            queries=list(self.sandbox.log.statements),
            gate_violations=list(self.sandbox.log.violations),
            raw=result,
        )


class TrackAStructured:
    name = "track_a_structured"

    def __init__(self, sandbox: SnapshotSandbox | None = None):
        self.sandbox = sandbox or SnapshotSandbox()

    def new_session(self, session_id: str) -> _TrackASession:
        from tools.analyst.conversation_state import clear_state

        clear_state(session_id)
        return _TrackASession(sandbox=self.sandbox, session_id=session_id, history=[])
