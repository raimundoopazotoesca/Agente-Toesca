"""Baseline/allowlist gate for pytest results.

Consumes the JSON produced by `tools.eval.pytest_nodeid_reporter` (exact
`report.nodeid` + phase + outcome + wasxfail records, the full collected
node-ID list, and synthetic "collect"/"internal" failure records) and
compares it against two committed JSON files for the `tests` suite:

- an immutable historical baseline (`eval/baselines/pytest-d986996.json`),
  pinned to commit d986996 and never edited after creation;
- an active, shrinking allowlist (`eval/baselines/pytest-known-failures.json`)
  of node IDs still permitted to fail.

`evaluate_run(records, historical, active_allowlist, collected_ids)` is the
authoritative comparison function. It never touches the system under test,
never calls an LLM/judge, and only reasons about pytest's own reporting
output.

Gate semantics (see docs/superpowers/plans/2026-08-31-eval-foundation-step-0.md
Global constraints and the Task 1 execution amendments):

- A `call` phase outcome `"failed"` (and not xfail) for an ID *not* on the
  active allowlist is a brand-new failure -> blocks, regardless of whether
  the total failure count went down elsewhere.
- A `call` phase outcome `"failed"` (not xfail) for an ID *on* the active
  allowlist is an allowed, visible, retained failure -> does not block.
- An active-allowlist ID that now `"passed"` is a *stale* allowlist entry:
  it must be removed from the allowlist in the same reviewed change, so it
  blocks until then.
- An active-allowlist ID in any other state -- SKIP, XFAIL, NOT-COLLECTED,
  setup/teardown ERROR, collection failure -- blocks and is never
  considered "resolved".
- A historical-baseline ID that has *already* been removed from the active
  allowlist (by an earlier, separately reviewed change) and is now
  confirmed passing is reported as `resolved_baseline_ids` for visibility,
  but does not block by itself.
- Any collection failure or internal error blocks unconditionally.

Regenerating `eval/baselines/pytest-d986996.json`: three tests
(`tests/db/test_ingest_er_{inmosa,sucden,apo3001}.py::test_parse_archivo_
real_no_lanza_y_cuadra_integridad`) are `skipif`-guarded on a proprietary,
OneDrive-synced xlsx file whose accessibility is flaky in time -- even
back-to-back runs on the same machine can disagree on whether it resolves.
Always regenerate with those 3 IDs passed to `--deselect`, then splice them
back into the manifest's `skip_ids` (never `failure_ids`) with reason
"archivo real no disponible o locked en este entorno". See the top-of-file
comment in `.github/workflows/eval-foundation.yml` and the `notes` field in
`eval/baselines/pytest-d986996.json` for the exact command and rationale.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REQUIRED_BASE_COMMIT = "d986996baf2636ff7978314f424614c5f33afc75"


class ManifestError(ValueError):
    """Raised when a baseline/allowlist manifest fails strict validation."""


def _validate_ids(ids: Iterable[Any], *, field_name: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in ids:
        if not isinstance(raw, str):
            raise ManifestError(f"{field_name} contains a non-string ID: {raw!r}")
        if raw == "":
            raise ManifestError(f"{field_name} contains an empty ID")
        if raw in seen:
            raise ManifestError(f"{field_name} contains a duplicate ID: {raw!r}")
        seen.add(raw)
        result.append(raw)
    return sorted(result)


def load_historical(path: str | Path) -> dict[str, Any]:
    """Strictly parse the immutable historical baseline manifest."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestError("historical manifest must be a JSON object")

    base_commit = data.get("base_commit")
    if base_commit != REQUIRED_BASE_COMMIT:
        raise ManifestError(
            f"historical manifest base_commit must be {REQUIRED_BASE_COMMIT!r}, "
            f"got {base_commit!r}"
        )

    command = data.get("command")
    if not isinstance(command, str) or not command:
        raise ManifestError("historical manifest missing non-empty 'command'")

    summary = data.get("summary")
    if not isinstance(summary, dict):
        raise ManifestError("historical manifest missing 'summary' object")

    failure_ids = _validate_ids(data.get("failure_ids", []), field_name="failure_ids")

    skip_entries = data.get("skip_ids", [])
    skip_ids = [
        entry["nodeid"] if isinstance(entry, dict) else entry for entry in skip_entries
    ]
    _validate_ids(skip_ids, field_name="skip_ids")

    return {
        "base_commit": base_commit,
        "command": command,
        "summary": summary,
        "failure_ids": failure_ids,
        "skip_ids": skip_entries,
    }


def load_allowlist(path: str | Path) -> list[str]:
    """Strictly parse the active, shrinking allowlist manifest."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        ids = data.get("failure_ids", [])
    elif isinstance(data, list):
        ids = data
    else:
        raise ManifestError("known-failures manifest must be a JSON object or array")
    return _validate_ids(ids, field_name="failure_ids")


@dataclass
class BaselineGateResult:
    new_failure_ids: list[str] = field(default_factory=list)
    allowed_failure_ids: list[str] = field(default_factory=list)
    stale_pass_ids: list[str] = field(default_factory=list)
    prohibited_state_ids: dict[str, str] = field(default_factory=dict)
    not_collected_ids: list[str] = field(default_factory=list)
    resolved_baseline_ids: list[str] = field(default_factory=list)
    collection_errors: list[str] = field(default_factory=list)
    internal_errors: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return bool(
            self.new_failure_ids
            or self.stale_pass_ids
            or self.prohibited_state_ids
            or self.not_collected_ids
            or self.collection_errors
            or self.internal_errors
        )

    @property
    def exit_code(self) -> int:
        return 1 if self.blocking else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_failure_ids": sorted(self.new_failure_ids),
            "allowed_failure_ids": sorted(self.allowed_failure_ids),
            "stale_pass_ids": sorted(self.stale_pass_ids),
            "prohibited_state_ids": dict(sorted(self.prohibited_state_ids.items())),
            "not_collected_ids": sorted(self.not_collected_ids),
            "resolved_baseline_ids": sorted(self.resolved_baseline_ids),
            "collection_errors": sorted(self.collection_errors),
            "internal_errors": sorted(self.internal_errors),
            "exit_code": self.exit_code,
        }


def _classify(phases: dict[str, dict[str, Any]]) -> str:
    """Classify one node ID's overall state from its phase records.

    Returns one of: "passed", "failed", "skipped", "xfail", "error",
    "not_run".
    """
    setup = phases.get("setup")
    call = phases.get("call")
    teardown = phases.get("teardown")

    if setup is not None and setup["outcome"] == "failed":
        return "error"
    if teardown is not None and teardown["outcome"] == "failed":
        return "error"

    if call is None:
        if setup is not None and setup["outcome"] == "skipped":
            return "xfail" if setup.get("wasxfail") else "skipped"
        return "not_run"

    outcome = call["outcome"]
    wasxfail = call.get("wasxfail")
    if outcome == "failed":
        return "xfail" if wasxfail else "failed"
    if outcome == "skipped":
        return "xfail" if wasxfail else "skipped"
    if outcome == "passed":
        return "xfail" if wasxfail else "passed"
    return "unknown"


def evaluate_run(
    records: list[dict[str, Any]],
    historical: dict[str, Any],
    active_allowlist: Iterable[str],
    collected_ids: Iterable[str],
) -> BaselineGateResult:
    """Compare one pytest run's exact node-ID records against the baseline.

    `records` is the full list of per-(nodeid, phase) records as produced by
    `tools.eval.pytest_nodeid_reporter` (including its synthetic "collect"
    and "internal" phase records for infrastructure failures).
    """
    result = BaselineGateResult()

    by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for rec in records:
        phase = rec["phase"]
        if phase == "collect":
            result.collection_errors.append(rec["nodeid"])
            continue
        if phase == "internal":
            result.internal_errors.append(rec["nodeid"])
            continue
        by_id.setdefault(rec["nodeid"], {})[phase] = rec

    collected_set = set(collected_ids)
    active_set = set(active_allowlist)
    historical_failure_ids = set(historical.get("failure_ids", []))

    for node_id in active_set:
        if node_id not in collected_set:
            result.not_collected_ids.append(node_id)
            continue
        state = _classify(by_id.get(node_id, {}))
        if state == "failed":
            result.allowed_failure_ids.append(node_id)
        elif state == "passed":
            result.stale_pass_ids.append(node_id)
        else:
            result.prohibited_state_ids[node_id] = state

    for node_id in historical_failure_ids - active_set:
        if node_id in collected_set and _classify(by_id.get(node_id, {})) == "passed":
            result.resolved_baseline_ids.append(node_id)

    for node_id, phases in by_id.items():
        if node_id in active_set:
            continue
        if _classify(phases) == "failed":
            result.new_failure_ids.append(node_id)

    return result


def _load_report(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestError("node-id report must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate a pytest run's exact node-ID results against an "
        "immutable historical baseline and an active, shrinking allowlist."
    )
    parser.add_argument(
        "--nodeid-report",
        required=True,
        help="Path to the JSON produced by tools.eval.pytest_nodeid_reporter "
        "(--nodeid-report output from the pytest run being gated).",
    )
    parser.add_argument(
        "--baseline",
        required=True,
        help="Path to the immutable historical baseline JSON "
        "(eval/baselines/pytest-d986996.json).",
    )
    parser.add_argument(
        "--known-failures",
        required=True,
        help="Path to the active allowlist JSON "
        "(eval/baselines/pytest-known-failures.json).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to also write the gate result JSON.",
    )
    args = parser.parse_args(argv)

    try:
        report = _load_report(args.nodeid_report)
        historical = load_historical(args.baseline)
        active_allowlist = load_allowlist(args.known_failures)
    except (ManifestError, OSError, json.JSONDecodeError) as exc:
        print(f"pytest_baseline_gate: manifest error: {exc}", file=sys.stderr)
        return 2

    result = evaluate_run(
        records=report.get("records", []),
        historical=historical,
        active_allowlist=active_allowlist,
        collected_ids=report.get("collected_ids", []),
    )

    payload = result.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    print(text)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
