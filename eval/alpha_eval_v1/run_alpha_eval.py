"""Alpha Product Validation v1 — real-flow runner.

Executes the 15 cases in cases.json against the REAL product flow
(ConversationService -> OpenAIResponsesAnalystSessionFactory -> gpt-5.6-terra),
exactly as wired in scripts/ingesta_server.py. No isolated components.

Captures per turn: visible answer, draft (pre-B.3) answer, tool calls, SQL
queries, token usage, latency, termination reason, presentation status.

First run is authoritative. On a provider/infra exception, one retry is
attempted and logged as a distinct event; it does not replace the first
attempt's record.

Safety: read-only DB access (LiveReadOnlySandbox, already enforced by the
production session factory). No writes to memory/agente_toesca_v2.db. No
migrations. Uses a throwaway workspace DB file so it does not touch
memory/analyst_workspace.db.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from tools.analyst_workspace.store import WorkspaceStore
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_runtime.session import OpenAIResponsesAnalystSessionFactory
from tools.analyst_runtime.presentation import OpenAIResponsesFinalPresenter, PresentationResult

CASES_PATH = Path(__file__).with_name("cases.json")
RESULTS_DIR = Path(__file__).with_name("results")
WORKSPACE_DB = Path(__file__).with_name("_scratch_workspace.db")
KNOWLEDGE_DB = REPO_ROOT / "memory" / "agente_toesca_v2.db"


class CapturingPresenter:
    """Wraps the real OpenAIResponsesFinalPresenter to record the draft
    (pre-B.3) text alongside the real, unmodified result it returns."""

    def __init__(self, client, model):
        self._inner = OpenAIResponsesFinalPresenter(client, model)
        self.last_draft: str | None = None
        self.last_result: PresentationResult | None = None
        self.invoked = False

    def present(self, *, user_message: str, draft_answer: str) -> PresentationResult:
        self.invoked = True
        self.last_draft = draft_answer
        result = self._inner.present(user_message=user_message, draft_answer=draft_answer)
        self.last_result = result
        return result


def make_presenter_factory(capture_slot: dict):
    def factory(client, model):
        presenter = CapturingPresenter(client, model)
        capture_slot["presenter"] = presenter
        return presenter
    return factory


def run_turn(service: ConversationService, conv_id: str, text: str, capture_slot: dict, retry_note: list):
    capture_slot["presenter"] = None
    started = time.monotonic()
    try:
        message = service.send_message(conv_id, text)
    except Exception as exc:  # noqa: BLE001 - infra/provider error path, logged then retried once
        err = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        retry_note.append({"turn": text, "error": err, "attempt": 1})
        time.sleep(2)
        started = time.monotonic()
        message = service.send_message(conv_id, text)
        retry_note.append({"turn": text, "note": "succeeded on retry", "attempt": 2})
    latency_ms = (time.monotonic() - started) * 1000
    presenter = capture_slot.get("presenter")
    draft = presenter.last_draft if presenter else None
    b3_invoked = bool(presenter and presenter.invoked)
    return {
        "user_message": text,
        "visible_answer": message.content,
        "draft_before_b3": draft,
        "b3_invoked": b3_invoked,
        "presentation_integrity_status": (presenter.last_result.integrity_status if presenter and presenter.last_result else None),
        "presentation_applied": (presenter.last_result.applied if presenter and presenter.last_result else None),
        "metadata": message.metadata,
        "wall_latency_ms": latency_ms,
    }


def main():
    if WORKSPACE_DB.exists():
        WORKSPACE_DB.unlink()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    RESULTS_DIR.mkdir(exist_ok=True)

    store = WorkspaceStore(WORKSPACE_DB)
    store.initialize()

    for case in cases:
        case_id = case["id"]
        print(f"=== running {case_id} ===", flush=True)
        capture_slot: dict = {}
        factory = OpenAIResponsesAnalystSessionFactory(
            KNOWLEDGE_DB,
            presenter_factory=make_presenter_factory(capture_slot),
        )
        service = ConversationService(store, factory)
        conv = service.create_conversation(title=case_id)
        retry_note: list = []
        turns_out = []
        case_started = time.monotonic()
        case_error = None
        try:
            for turn_text in case["turns"]:
                turns_out.append(run_turn(service, conv.id, turn_text, capture_slot, retry_note))
        except Exception as exc:  # noqa: BLE001
            case_error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        case_total_ms = (time.monotonic() - case_started) * 1000

        out = {
            "id": case_id,
            "category": case["category"],
            "ground_truth": case["ground_truth"],
            "expected_behavior": case["expected_behavior"],
            "turns": turns_out,
            "retries": retry_note,
            "case_error": case_error,
            "case_total_latency_ms": case_total_ms,
        }
        out_path = RESULTS_DIR / f"{case_id}.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    -> {out_path.name} ({case_total_ms:.0f} ms, {len(turns_out)} turns)", flush=True)

    print("done")


if __name__ == "__main__":
    main()
