"""Build the offline, blinded Round B eight-candidate screening package.

This module deliberately reads candidate evidence only from the validated
external archive.  Runtime cache is consulted only by ``validate`` to prove
the archive was copied byte-for-byte.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.benchmark.cases_loader import CASES_DIR, load_cases

ARCHIVE = Path(r"C:\Users\raimundo.opazo\toesca-benchmark-archives\round-b-screening-8-20260818")
SOURCE = Path(r"C:\Users\raimundo.opazo\.codex\worktrees\toesca-analyst-round-b\eval\benchmark\.cache\round-b-results")
REPORTS = Path(__file__).resolve().parents[1] / "benchmark" / "reports" / "round_b_screening_8"
SEED = 20260818
RUNS = {
    "round-b-20260817-b6": {"turns": "e7eb71b1b8b029d0f4a209d9d70bd5993c0663128f8df9298654a97cef0c0d45", "events": "19fe6d3fd82a7ba9379f3cbdd75b771f73bbae0082a001c852040964348cd994"},
    "round-b-20260817-b8": {"turns": "b9b14882829d64d80886b13bcb225cec351b659940462fae8e81397dccbfd17c", "events": "6b2cf68379d41890181056d8ef68277eab890e0d68dc4be087f42a29f8e836bd"},
    "round-b-20260817-b10": {"turns": "8c5afe336d921f55ec685a5be910d034942a78784484d7a08b25ac3743604022", "events": "9576f74819f29fc6d6283c6294f76b88b012dcbe1b99a41f4df39b4c2b2ca341"},
    "round-b-20260817-b11": {"turns": "7735bdb399e62be6df1b93a72d261bf1e335668a5303a54afffebd6e6c09aab2", "events": "abc287aa6c06f4200e6ef4b0914201ad3c996d62e3601b73fcbf72da74191a18"},
    "round-b-20260818-b12": {"turns": "650a9e53f5ca349aeeff1ed23813256bc63561b45a6fa6b5718e78b69cbad9ee", "events": "58635f7c8ecf4d6aa0339479999c677871979cb99503f4884495d99431b521eb"},
    "round-b-20260818-b19": {"turns": "d95a8541130bb3e20b09a0f5dde5a8b8c6966364ec80696d1f04ca0a9e88522d", "events": "dd13da7025063e7d0633c67f057078e0407184c4b559c6c416374c7295f75fe2"},
    "round-b-20260818-b20": {"turns": "289e81dab452f6983a4bf4811f12ec85e717dccc761554760d9c2f22926a47a6", "events": "3b4e7fca419fae6d84f298cb6bbaad162ef27dc3cda646eb5ad4f9b952ffcce5"},
}
PRIVATE = {"reasoning_content", "thinking", "redacted_thinking", "signature", "thought_signature"}
REVEALING = {"provider", "requested_model", "resolved_model", "run_id", "candidate_id", "latency_ms", "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("type") in {"reasoning", "thinking", "redacted_thinking"}:
            return None
        return {k: child for k, item in value.items() if k.lower() not in PRIVATE and (child := scrub(item)) is not None}
    if isinstance(value, list):
        return [child for item in value if (child := scrub(item)) is not None]
    return value


def validate_archive() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for run_id, expected in RUNS.items():
        for name in ("turns", "events"):
            rel = Path(run_id) / f"{name}.jsonl"
            archived, source = ARCHIVE / rel, SOURCE / rel
            actual = sha256(archived)
            if actual != expected[name] or sha256(source) != actual or archived.read_bytes() != source.read_bytes():
                raise RuntimeError(f"archive validation failed: {rel}")
            files.append({"archived_relative_path": str(rel).replace("\\", "/"), "source_absolute_path": str(source), "size": archived.stat().st_size, "sha256": actual})
        rel = Path(run_id) / "checkpoint.json"
        archived, source = ARCHIVE / rel, SOURCE / rel
        if sha256(archived) != sha256(source) or archived.read_bytes() != source.read_bytes():
            raise RuntimeError(f"archive validation failed: {rel}")
        files.append({"archived_relative_path": str(rel).replace("\\", "/"), "source_absolute_path": str(source), "size": archived.stat().st_size, "sha256": sha256(archived)})
    return {"status": "PASS", "files": files}


def candidate_rows() -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded: list[dict[str, Any]] = []
    for run_id in RUNS:
        for row in read_jsonl(ARCHIVE / run_id / "turns.jsonl"):
            identity = "|".join(str(row[k]) for k in ("provider", "requested_model", "resolved_model", "candidate_id"))
            if run_id.endswith("b6") and row["provider"] == "mistral":
                excluded.append({"run_id": run_id, "identity": identity, "case_id": row["case_id"], "turn_index": row["turn_index"], "reason": "historical partial Mistral row"})
            else:
                grouped[identity].append(row)
    if len(grouped) != 8:
        raise RuntimeError(f"expected eight complete candidates, got {len(grouped)}")
    for identity, rows in grouped.items():
        if len(rows) != 25 or len({r["case_id"] for r in rows}) != 15:
            raise RuntimeError(f"incomplete candidate: {identity}")
    return dict(grouped), excluded


def create_manifest() -> None:
    checked = validate_archive()
    grouped, excluded = candidate_rows()
    identities = []
    for identity, rows in sorted(grouped.items()):
        first = rows[0]
        identities.append({"identity": identity, "provider": first["provider"], "requested_model": first["requested_model"], "resolved_model": first["resolved_model"], "candidate_id": first["candidate_id"], "turn_count": len(rows), "case_count": len({r["case_id"] for r in rows})})
    manifest = {"archive_id": "round-b-screening-8-20260818", "created_at": datetime.now(timezone.utc).isoformat(), "source_absolute_path": str(SOURCE), "files": checked["files"], "candidate_identities": identities, "excluded_historical_rows": excluded, "validation_status": checked["status"]}
    (ARCHIVE / "archive_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_blind() -> None:
    grouped, excluded = candidate_rows()  # archive only
    identities = sorted(grouped)
    random.Random(SEED).shuffle(identities)
    mapping = {f"Candidate {chr(65 + i)}": identity for i, identity in enumerate(identities)}
    if len(mapping) != 8 or len(set(mapping.values())) != 8:
        raise RuntimeError("mapping is not one-to-one")
    cases = {case.id: case for case in load_cases(CASES_DIR, split="dev")}
    package: dict[str, Any] = {"seed": SEED, "privacy": "hidden reasoning and provider replay fields removed", "candidates": {}}
    validation: dict[str, Any] = {"status": "PASS", "seed": SEED, "labels": sorted(mapping), "candidate_checks": [], "excluded_historical_rows": excluded}
    for label, identity in mapping.items():
        rows = sorted(grouped[identity], key=lambda r: (r["case_id"], r["turn_index"]))
        turns = []
        for row in rows:
            case = cases[row["case_id"]]
            turn = case.turns[row["turn_index"]]
            visible = scrub({k: v for k, v in row.items() if k not in REVEALING})
            refs = {fact["ref"] for fact in turn.get("required_facts", []) + turn.get("acceptable_facts", [])}
            turns.append({
                "case_id": row["case_id"], "turn_index": row["turn_index"], "question": turn["question"],
                "conversation_context": [prior["question"] for prior in case.turns[:row["turn_index"]]],
                "final_answer": visible.get("final_answer"), "executed_sql": visible.get("executed_sql", []),
                "tool_calls": visible.get("tool_calls", []), "deterministic_grading": visible.get("deterministic_grading", {}),
                "expected_behavior": turn.get("expected_behavior", []), "required_facts": turn.get("required_facts", []),
                "forbidden_claims": turn.get("forbidden_claims", []),
                "grounding_facts": {ref: case.ground_truth_refs[ref].get("description", ref) for ref in refs},
            })
        package["candidates"][label] = {"turns": turns}
        validation["candidate_checks"].append({"label": label, "turn_count": len(rows), "case_count": len({r["case_id"] for r in rows}), "identity_checks": [{"case_id": r["case_id"], "turn_index": r["turn_index"]} for r in rows[:3]]})
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "blind_package.json").write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPORTS / "blind_mapping.hidden.json").write_text(json.dumps({"seed": SEED, "mapping": mapping}, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "mapping_validation.json").write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def reveal() -> None:
    """Produce the reveal only from the frozen record and hidden mapping."""
    frozen = json.loads((REPORTS / "blind_evaluation.freeze.json").read_text(encoding="utf-8"))
    mapping = json.loads((REPORTS / "blind_mapping.hidden.json").read_text(encoding="utf-8"))["mapping"]
    current = sha256(REPORTS / "blind_evaluation.md")
    if current != frozen["blind_evaluation_sha256"]:
        raise RuntimeError("blind evaluation changed after freeze")
    report = {
        "reveal_generated_after_freeze": True,
        "blind_evaluation_sha256_expected": frozen["blind_evaluation_sha256"],
        "blind_evaluation_sha256_actual": current,
        "ranking_a_unchanged": frozen["ranking_a"],
        "ranking_b_unchanged": frozen["ranking_b"],
        "mapping": mapping,
    }
    (REPORTS / "reveal_report.md").write_text("# Round B screening 8 — reveal\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "manifest", "blind", "reveal"))
    args = parser.parse_args()
    if args.command == "validate": print(json.dumps(validate_archive(), indent=2))
    elif args.command == "manifest": create_manifest()
    elif args.command == "blind": build_blind()
    else: reveal()


if __name__ == "__main__": main()
