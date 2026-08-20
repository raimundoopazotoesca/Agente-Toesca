from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProductCase:
    id: str
    turns: tuple[str, ...]
    purpose: str
    deterministic: dict[str, object]
    semantic: dict[str, object]
    prohibited: dict[str, object]
    capabilities: frozenset[str] = frozenset()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrialEvidence:
    """Offline evidence supplied by a future runtime adapter; it never invokes one."""

    response_text: str
    capabilities: frozenset[str] = frozenset()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    passed: bool
    failed_constraints: tuple[str, ...] = ()
