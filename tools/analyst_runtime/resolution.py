"""Public, diagnostic-preserving resolution outcomes for A2 traces."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

ResolutionStatus = Literal["resolved", "ambiguous", "unknown"]


@dataclass(frozen=True)
class ResolutionOutcome:
    status: ResolutionStatus
    canonical_value: str | None = None
    method: str = "unavailable"
    reason_code: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    candidates: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "status": self.status,
            "method": self.method,
            "evidence": dict(self.evidence),
            "candidates": [dict(candidate) for candidate in self.candidates],
        }
        if self.canonical_value is not None:
            data["canonical_value"] = self.canonical_value
        if self.reason_code is not None:
            data["reason_code"] = self.reason_code
        return data


def resolution_from_entity_payload(payload: Mapping[str, Any], trace: Mapping[str, Any]) -> ResolutionOutcome:
    internal = str(payload.get("status") or trace.get("status") or "not_found")
    candidates = tuple(dict(candidate) for candidate in payload.get("candidates", ()) if isinstance(candidate, Mapping))
    evidence = {"internal_status": internal}
    if trace.get("query") is not None:
        evidence["query"] = trace["query"]
    if internal == "resolved":
        candidate = candidates[0] if candidates else {}
        return ResolutionOutcome(
            "resolved",
            str(candidate.get("entity_key")) if candidate.get("entity_key") is not None else None,
            str(candidate.get("match_kind") or "entity_resolver"),
            evidence=evidence,
            candidates=candidates,
        )
    if internal == "ambiguous":
        return ResolutionOutcome("ambiguous", method="entity_resolver", evidence=evidence, candidates=candidates)
    return ResolutionOutcome("unknown", method="entity_resolver", reason_code=internal, evidence=evidence, candidates=candidates)


def unavailable_resolution(reason_code: str = "not_observed") -> ResolutionOutcome:
    return ResolutionOutcome("unknown", reason_code=reason_code)

