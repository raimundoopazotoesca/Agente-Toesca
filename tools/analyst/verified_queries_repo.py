"""Verified-query lookup: lexical token-overlap similarity over
tools/analyst/verified_queries/*.yaml. No embeddings in this phase."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

VERIFIED_QUERIES_DIR = Path(__file__).resolve().parent / "verified_queries"

_WORD_RE = re.compile(r"[a-záéíóúñ0-9]+", re.IGNORECASE)


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _load_all(repo_dir: Path) -> list[dict]:
    entries = []
    for path in sorted(repo_dir.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as fh:
            entries.append(yaml.safe_load(fh))
    return entries


def find_similar(question: str, top_k: int = 1, repo_dir: Path | None = None) -> list[dict]:
    repo_dir = repo_dir or VERIFIED_QUERIES_DIR
    query_tokens = _tokenize(question)
    scored = []
    for entry in _load_all(repo_dir):
        candidate_tokens = _tokenize(entry["question"])
        union = query_tokens | candidate_tokens
        overlap = query_tokens & candidate_tokens
        score = len(overlap) / len(union) if union else 0.0
        scored.append({**entry, "score": score})
    scored.sort(key=lambda e: e["score"], reverse=True)
    return [e for e in scored[:top_k] if e["score"] > 0]
