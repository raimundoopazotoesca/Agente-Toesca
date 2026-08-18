"""Frozen Mini-Dev Round B execution; no qualitative judge or fallback."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
import os
import re
from pathlib import Path
from typing import Any

import yaml

from eval.benchmark.adapters.track_b_frontier import B1_STANDARD_PROFILES, _RUN_SQL_TOOL, _SYSTEM_PROMPT_TEMPLATE, _schema_summary, _semantic_context
from eval.benchmark.adapters.track_b_frontier import TrackBFrontier
from eval.benchmark.adapters.track_b_anthropic import TrackBAnthropic
from eval.benchmark.adapters.track_b_openai_responses import TrackBOpenAIResponses
from eval.benchmark.cases_loader import CASES_DIR, load_cases
from eval.benchmark.graders.deterministic import score_turn
from eval.benchmark.graders.ground_truth import resolve_ground_truth
from eval.benchmark.snapshot import SnapshotSandbox
from eval.round_b.incremental import IncrementalStore
from eval.benchmark.snapshot import load_lock

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "eval/round_b/mini_dev_v1.yaml"
PRICING = ROOT / "eval/round_b/pricing.yaml"
CANONICAL_SHA = "df8cd68c690266e770210e752ab8078ef8f3dc23b175e55abe97963a18d3558f"


def _canonical_hash(data: dict[str, Any]) -> str:
    content = {k: v for k, v in data.items() if k != "content_sha256"}
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_mini_dev(path: Path = MANIFEST) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    actual = _canonical_hash(data)
    if actual != CANONICAL_SHA or data.get("content_sha256") != CANONICAL_SHA:
        raise ValueError(f"Mini-Dev canonical hash mismatch: {actual}")
    return {"mini_dev_id": data["mini_dev_id"], "canonical_manifest_sha256": actual,
            "case_count": len(data["ordered_case_ids"]), "turn_count": sum(data["turn_counts"].values()),
            "ordered_case_ids": data["ordered_case_ids"], "snapshot_sha256": data["dev_freeze"]["snapshot_sha256"]}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _effective_contract_hashes() -> tuple[str, str]:
    """UTF-8 exact rendered prompt; canonical JSON tool schema (sorted keys, compact separators)."""
    sandbox = SnapshotSandbox()
    prompt = _SYSTEM_PROMPT_TEMPLATE.format(semantic_context=_semantic_context(), schema_summary=_schema_summary(sandbox))
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    tool = json.dumps(_RUN_SQL_TOOL, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return prompt_hash, hashlib.sha256(tool.encode("utf-8")).hexdigest()


def build_run_manifest(run_id: str, code_commit_sha: str, execution_date: str) -> dict[str, Any]:
    mini = validate_mini_dev()
    lock = load_lock()
    prompt_hash, tool_hash = _effective_contract_hashes()
    return {"run_id": run_id, "run_kind": "mini_dev", "mini_dev": mini, "code_commit_sha": code_commit_sha, "track": "B",
            "snapshot": lock, "system_prompt_sha256": prompt_hash, "tool_schema_sha256": tool_hash,
            "inference_profile": "B1_STANDARD", "provider_configs": [p.__dict__ for p in B1_STANDARD_PROFILES],
            "max_model_tool_rounds": 5, "timeout_policy": "provider default", "retry_policy": "one: 429/5xx/network/timeout",
            "grader_versions": {"deterministic_py_sha256": _file_hash(ROOT / "eval/benchmark/graders/deterministic.py"),
                                "gates_py_sha256": _file_hash(ROOT / "eval/benchmark/graders/gates.py")},
            "judge_status": "not_scored_yet", "execution_date": execution_date}


def estimate_cost(provider: str, model: str, input_tokens: int | None, output_tokens: int | None, cached_tokens: int | None) -> dict[str, Any] | None:
    if input_tokens is None or output_tokens is None:
        return None
    prices = yaml.safe_load(PRICING.read_text(encoding="utf-8"))["providers"]
    row = next((p for p in prices if p["provider"] == provider and p["model"] == model), None)
    if not row or not isinstance(row["input_per_mtok"], (int, float)) or not isinstance(row["output_per_mtok"], (int, float)):
        return None
    amount = input_tokens / 1e6 * row["input_per_mtok"] + output_tokens / 1e6 * row["output_per_mtok"]
    if cached_tokens and isinstance(row.get("cached_input_per_mtok"), (int, float)):
        amount -= cached_tokens / 1e6 * row["input_per_mtok"]
        amount += cached_tokens / 1e6 * row["cached_input_per_mtok"]
    return {"currency": row["currency"], "amount": round(amount, 8)}


def committed_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


CANDIDATES = {"groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"), "fireworks": ("FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1"), "nvidia": ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1"), "dashscope": ("DASHSCOPE_API_KEY", None), "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1"), "sambanova": ("SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1"), "openai": ("OPENAI_API_KEY", None), "anthropic": ("ANTHROPIC_API_KEY", None)}


def classify_execution_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "429" in text or "rate limit" in text or "quota" in text:
        return "quota_rate_limit"
    if re.search(r"\b5\d{2}\b", text):
        return "provider_infra"
    if "timeout" in text:
        return "timeout"
    if "connection" in text or "network" in text:
        return "provider_infra"
    if "sql" in text:
        return "tool_sql_invalid"
    return "adapter_protocol"


def is_retry_eligible(exc: Exception) -> bool:
    return classify_execution_error(exc) in {"quota_rate_limit", "provider_infra", "timeout"}


class RoundBRunner:
    """Persists deterministic-only Mini-Dev evidence; adapter is injectable for tests."""
    def __init__(self, adapter_factory, output_root: Path, run_id: str | None = None):
        self.adapter_factory, self.output_root = adapter_factory, output_root
        self.run_id = run_id or f"round-b-{uuid.uuid4().hex[:12]}"

    def preflight(self, code_sha: str) -> dict[str, Any]:
        if code_sha != committed_head():
            raise ValueError("code SHA is not current HEAD")
        return build_run_manifest(self.run_id, code_sha, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def _cases(self):
        checked = validate_mini_dev()
        all_cases = {c.id: c for c in load_cases(CASES_DIR, split="dev")}
        selected = [all_cases[x] for x in checked["ordered_case_ids"]]
        if sum(len(c.turns) for c in selected) != 25:
            raise ValueError("frozen Mini-Dev turn count drift")
        return selected

    def run_candidate(self, provider: str, model: str, code_sha: str) -> Path:
        profile = next((p for p in B1_STANDARD_PROFILES if p.provider == provider and p.model == model), None)
        if profile is None:
            raise ValueError("candidate is not B1_STANDARD")
        run_dir = self.output_root / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = self.preflight(code_sha)
        manifest_path = run_dir / "run_manifest.json"
        if not manifest_path.exists():
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        adapter = self.adapter_factory(provider, model, profile)
        sandbox = adapter.sandbox
        records: list[dict[str, Any]] = []
        for case in self._cases():
            session = adapter.new_session(f"{self.run_id}-{provider}-{case.id}")
            resolved = resolve_ground_truth(case, sandbox) if case.ground_truth_refs else {}
            for turn_index, turn_spec in enumerate(case.turns):
                retries, error, turn = 0, None, None
                for attempt in range(2):
                    try:
                        turn = session.ask(turn_spec["question"])
                        break
                    except Exception as exc:  # network boundary only
                        error = classify_execution_error(exc)
                        if attempt == 0 and is_retry_eligible(exc):
                            retries = 1
                            continue
                        break
                if turn is None:
                    records.append({"run_id": self.run_id, "candidate_id": provider, "case_id": case.id, "turn_index": turn_index,
                        "provider": provider, "requested_model": model, "resolved_model": None, "final_answer": "", "status": "failed",
                        "error_taxonomy": error, "model_rounds": 0, "tool_calls": [], "executed_sql": [], "input_tokens": None,
                        "output_tokens": None, "reasoning_tokens": None, "cached_tokens": None, "latency_ms": None, "retries": retries,
                        "deterministic_grading": None, "fatal_gates": [], "ceiling_gates": []})
                    continue
                scored = score_turn(turn, turn_spec, resolved)
                verdict = scored.gate_verdict
                usage = turn.usage
                records.append({"run_id": self.run_id, "candidate_id": provider, "case_id": case.id, "turn_index": turn_index,
                    "provider": provider, "requested_model": model, "resolved_model": usage.model, "final_answer": turn.text, "status": "completed",
                    "error_taxonomy": None, "model_rounds": usage.calls, "tool_calls": [x.__dict__ for x in turn.tool_calls], "executed_sql": turn.queries,
                    "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "reasoning_tokens": usage.reasoning_tokens,
                    "cached_tokens": usage.cached_tokens, "latency_ms": usage.latency_ms, "retries": retries,
                    "deterministic_grading": {"dimension_scores": scored.dimension_scores, "unscored_dimensions": sorted(scored.unscored_dimensions),
                        "facts_missing": scored.facts_missing}, "fatal_gates": [x.gate for x in (verdict.fatal_triggered if verdict else [])],
                    "ceiling_gates": [x.gate for x in (verdict.ceiling_triggered if verdict else [])]})
        path = run_dir / f"{provider}_{model.replace('/', '_')}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        return path

    def run_case(self, provider: str, model: str, case_id: str, code_sha: str, store: IncrementalStore) -> None:
        """One safe shard; completed/aborted cases are never replayed."""
        profile = next((p for p in B1_STANDARD_PROFILES if p.provider == provider and p.model == model), None)
        if profile is None: raise ValueError("candidate/model is not frozen B1_STANDARD")
        cases = {c.id: c for c in self._cases()}
        if case_id not in cases: raise ValueError("case is not in frozen Mini-Dev")
        if store.run_id != self.run_id: raise ValueError("store run id mismatch")
        store.begin_case(provider, case_id)
        case = cases[case_id]; adapter = self.adapter_factory(provider, model, profile)
        active: dict[int, str] = {}
        attempt = [0]
        def observe(kind, model_round, payload):
            if kind == "provider_request_started":
                active[model_round] = store.event(kind, provider, case_id, current_turn[0], model_round, attempt[0], requested_model=model)["event_id"]
            else:
                store.event(kind, provider, case_id, current_turn[0], model_round, attempt[0], request_event_id=active.pop(model_round), resolved_model=model)
        adapter.request_observer = observe
        session = adapter.new_session(f"{self.run_id}-{provider}-{case_id}")
        resolved = resolve_ground_truth(case, adapter.sandbox) if case.ground_truth_refs else {}
        try:
            current_turn = [0]
            for index, spec in enumerate(case.turns):
                current_turn[0] = index
                for attempt[0] in range(2):
                    try:
                        turn = session.ask(spec["question"]); break
                    except Exception as exc:
                        if attempt[0] == 0 and is_retry_eligible(exc): continue
                        store.set_state(provider, case_id, "aborted"); raise
                grade = score_turn(turn, spec, resolved)
                store.turn({"candidate_id": provider, "case_id": case_id, "turn_index": index, "provider": provider, "requested_model": model, "resolved_model": turn.usage.model, "final_answer": turn.text, "status": "completed", "model_rounds": turn.usage.calls, "tool_calls": [x.__dict__ for x in turn.tool_calls], "executed_sql": turn.queries, "input_tokens": turn.usage.input_tokens, "output_tokens": turn.usage.output_tokens, "reasoning_tokens": turn.usage.reasoning_tokens, "cached_tokens": turn.usage.cached_tokens, "latency_ms": turn.usage.latency_ms, "deterministic_grading": {"dimension_scores": grade.dimension_scores, "unscored_dimensions": sorted(grade.unscored_dimensions)}})
            store.complete_case(provider, case_id)
        except Exception:
            if store.checkpoint().get(provider, {}).get(case_id) == "running": store.set_state(provider, case_id, "aborted")
            raise


def live_adapter_factory(provider: str, model: str, profile):
    key_name, base_url = CANDIDATES[provider]
    if provider == "dashscope":
        base_url = os.environ.get("DASHSCOPE_BASE_URL")
    if not os.environ.get(key_name) or (not base_url and provider not in {"openai", "anthropic"}):
        raise RuntimeError("credential_missing")
    config = {"api_key": os.environ[key_name], "model": model}
    if base_url:
        config["base_url"] = base_url
    if provider == "anthropic":
        return TrackBAnthropic(provider=config)
    if provider == "openai":
        return TrackBOpenAIResponses(provider=config)
    return TrackBFrontier(provider=config, inference_profile=profile)
