"""Provider-neutral contract between AnalystLoop and one model call.

Moved from eval/benchmark/adapters/_transport.py (Stage A1) byte-for-byte.
F4 Stage 2's whole point: three reasoning loops (Chat Completions, OpenAI
Responses, Anthropic Messages) duplicated the same round-budget/synthesis
structure around three different wire protocols. This module is the seam --
everything on the AnalystLoop side of it is reasoning policy; everything on
the transport side of it is provider translation. Neither may leak into the
other (see analyst_loop.py's module docstring for the enforcement side of
that rule).

The one deliberately-imprecise field is `TranscriptItem.raw` / `ModelResponse
.raw_items`: opaque payload a transport needs echoed back verbatim on the next
call (OpenAI Responses' reasoning items, Anthropic's thinking/signature
blocks). AnalystLoop stores and replays it without ever inspecting it.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Protocol

from tools.analyst_runtime.base import Usage


@dataclass(frozen=True)
class ToolSpec:
    """One callable tool, in the shape a function-calling API expects:
    name + description + JSON Schema parameters."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolRequest:
    """One tool invocation the model asked for, already decoded from
    whatever wire shape the provider used."""

    call_id: str
    name: str
    arguments: dict[str, Any]


#: A3.2a contract version stamp for evidence produced by this codebase.
#: Bumped when the *shape* of ToolEvidence changes, not per commit.
EVIDENCE_CONTRACT_VERSION = "1"

_EVIDENCE_CLASSES = frozenset({"canonical_metric", "governed_dataset", "verified_query", "controlled_sql"})
_RESULT_KINDS = frozenset({"scalar", "table", "empty", "metadata"})


@dataclass(frozen=True)
class Producer:
    """Which tool produced this evidence, under which contract shape."""

    tool_name: str
    contract_version: str = EVIDENCE_CONTRACT_VERSION


@dataclass(frozen=True)
class Authority:
    """What backs this evidence's claim to be governed, not raw/ad hoc.

    ``kind`` always equals the owning ToolEvidence's ``evidence_class`` --
    it is a self-sufficiency echo (a consumer holding only this sub-block
    can still tell what governs it), not a second, independently-varying
    taxonomy. See the A3.2 semantic decision memo, section 4.

    Every ``*_id``/``*_version`` field is optional and MUST be left None
    when no genuine catalog-backed identity exists -- a raw SQL table name
    is never a valid ``dataset_id``, and no version is ever fabricated when
    the underlying catalog does not track one yet.
    """

    kind: str
    source_system: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    metric_id: str | None = None
    metric_version: str | None = None
    verified_query_id: str | None = None
    verified_query_version: str | None = None
    sql_fingerprint: str | None = None


@dataclass(frozen=True)
class Temporal:
    """Evidence-level summary window -- derived from the facts already
    present, never authored independently. Per-fact period stays on
    ``facts[i]["period"]``; this is a summary of that, not a replacement.
    ``observed_as_of`` is left None rather than fabricated when no real
    refresh timestamp is available."""

    requested: dict[str, Any] | None = None
    resolved: dict[str, Any] | None = None
    observed_as_of: str | None = None
    granularity: str | None = None


@dataclass(frozen=True)
class Units:
    """Evidence-level unit summary, populated only when every fact shares
    one unit/scale/basis. Left fully None (never a first-wins guess) when
    facts carry heterogeneous units -- consumers fall back to the
    per-fact/per-row unit in that case."""

    unit: str | None = None
    scale: str | None = None
    basis: str | None = None


@dataclass(frozen=True)
class ResultEnvelope:
    """The bounded, model/reader-visible display projection of this
    evidence. For ``canonical_metric``/``governed_dataset``/``verified_query``
    this is mechanically derived from ``facts`` (same data, table-shaped);
    for ``controlled_sql`` it is the primary, literal bounded query output
    (``facts`` stays ``()`` there -- see the ``controlled_sql`` invariant).

    ``total_rows`` stays ``None`` unless it is actually known -- never
    computed via an implicit COUNT query."""

    kind: str  # "scalar" | "table" | "empty" | "metadata"
    columns: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    total_rows: int | None = None
    returned_rows: int = 0
    truncated: bool = False
    has_more: bool = False
    omission_reason: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _RESULT_KINDS:
            raise ValueError(f"ResultEnvelope.kind must be one of {sorted(_RESULT_KINDS)}, got {self.kind!r}")


@dataclass(frozen=True)
class ToolEvidence:
    """The sole citeable evidence object. Technical errors are never
    represented here -- they belong on ``ToolResult.content``/``trace``/
    ``control`` instead (see ``ToolResult``'s ``ok=False -> evidence=None``
    invariant)."""

    evidence_id: str
    evidence_class: str
    producer: Producer
    authority: Authority
    scope: dict[str, Any]
    temporal: Temporal
    units: Units
    result: ResultEnvelope
    facts: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    coverage: dict[str, Any] | None = None
    semantic_contract: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evidence_class not in _EVIDENCE_CLASSES:
            raise ValueError(f"evidence_class must be one of {sorted(_EVIDENCE_CLASSES)}, got {self.evidence_class!r}")
        if self.authority.kind != self.evidence_class:
            raise ValueError(
                f"authority.kind ({self.authority.kind!r}) must equal evidence_class ({self.evidence_class!r})")
        if self.evidence_class == "controlled_sql" and self.facts:
            raise ValueError("controlled_sql evidence must have facts == () -- ungoverned SQL output is not a bound claim")

    @classmethod
    def build(cls, *, evidence_id: str, evidence_class: str, tool_name: str,
              source_kind: str | None, scope: dict[str, Any], semantic_contract: dict[str, Any],
              provenance: dict[str, Any], facts: tuple[dict[str, Any], ...],
              coverage: dict[str, Any] | None = None, metric_id: str | None = None,
              dataset_id: str | None = None, requested_temporal: dict[str, Any] | None = None,
              granularity: str = "month", limitations: tuple[str, ...] = ()) -> "ToolEvidence":
        """Construct evidence from what today's producers already compute,
        deriving ``temporal``/``units``/``result`` from ``facts`` rather than
        requiring each producer to author them by hand.

        ``metric_id``/``dataset_id`` must only be passed when they name a
        real catalog-backed identity (metric catalog key, dataset-catalog
        key, account-concept id) -- never a raw table name. Leave them
        ``None`` when no such identity exists today.
        """
        return cls(
            evidence_id=evidence_id, evidence_class=evidence_class,
            producer=Producer(tool_name=tool_name),
            authority=Authority(kind=evidence_class, source_system=source_kind,
                                 metric_id=metric_id, dataset_id=dataset_id),
            scope=scope, temporal=_derive_temporal(facts, requested_temporal, granularity),
            units=_derive_units(facts), result=_derive_result(facts),
            facts=facts, provenance=provenance, limitations=limitations,
            coverage=coverage, semantic_contract=semantic_contract,
        )


def _derive_temporal(facts: tuple[dict[str, Any], ...], requested: dict[str, Any] | None,
                      granularity: str) -> Temporal:
    periods = sorted({fact["period"] for fact in facts if fact.get("period") is not None})
    resolved = {"start": periods[0], "end": periods[-1]} if periods else None
    # No independent "requested" signal was supplied: the honest summary is
    # what was actually resolved, not a fabricated different value.
    return Temporal(requested=requested if requested is not None else resolved,
                     resolved=resolved, observed_as_of=None, granularity=granularity if periods or requested else None)


def _derive_units(facts: tuple[dict[str, Any], ...]) -> Units:
    units = {fact["unit"] for fact in facts if fact.get("unit") is not None}
    return Units(unit=next(iter(units))) if len(units) == 1 else Units()


def _derive_result(facts: tuple[dict[str, Any], ...]) -> ResultEnvelope:
    if not facts:
        return ResultEnvelope(kind="empty", columns=(), rows=(), total_rows=0, returned_rows=0)
    columns = tuple(sorted({key for fact in facts for key in fact}))
    rows = tuple(dict(fact) for fact in facts)
    kind = "scalar" if len(facts) == 1 else "table"
    return ResultEnvelope(kind=kind, columns=columns, rows=rows, total_rows=len(facts),
                           returned_rows=len(facts), truncated=False, has_more=False)


_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))


def _to_serializable(value: Any) -> Any:
    """Deterministically reduce a ToolEvidence (or any nested piece of it) to
    plain dict/list/scalar JSON-safe structures. Raises TypeError on
    anything else -- an arbitrary Python object, a provider payload, a
    datetime, etc. -- so evidence can never carry unbounded/unsafe content
    into serialization."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_serializable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(key): _to_serializable(val) for key, val in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(item) for item in value]
    if isinstance(value, _JSON_SCALAR_TYPES):
        return value
    raise TypeError(f"non-serializable evidence payload type: {type(value).__name__}")


def evidence_to_dict(evidence: ToolEvidence) -> dict[str, Any]:
    """The one supported serialization path for ToolEvidence: deterministic,
    bounded, free of arbitrary objects/secrets/provider payloads/CoT by
    construction (every leaf is a JSON scalar)."""
    return _to_serializable(evidence)


def evidence_from_dict(data: dict[str, Any]) -> ToolEvidence:
    """Round-trip counterpart to ``evidence_to_dict``. Rejects a payload
    missing required structure rather than silently defaulting it."""
    if not isinstance(data, dict):
        raise TypeError("evidence_from_dict requires a dict payload")

    def _get(mapping: dict[str, Any], key: str) -> Any:
        if key not in mapping:
            raise ValueError(f"evidence payload missing required field: {key!r}")
        return mapping[key]

    producer_data = _get(data, "producer")
    authority_data = _get(data, "authority")
    temporal_data = _get(data, "temporal")
    units_data = _get(data, "units")
    result_data = _get(data, "result")
    return ToolEvidence(
        evidence_id=str(_get(data, "evidence_id")),
        evidence_class=str(_get(data, "evidence_class")),
        producer=Producer(tool_name=str(producer_data["tool_name"]),
                           contract_version=str(producer_data.get("contract_version", EVIDENCE_CONTRACT_VERSION))),
        authority=Authority(
            kind=str(authority_data["kind"]), source_system=authority_data.get("source_system"),
            dataset_id=authority_data.get("dataset_id"), dataset_version=authority_data.get("dataset_version"),
            metric_id=authority_data.get("metric_id"), metric_version=authority_data.get("metric_version"),
            verified_query_id=authority_data.get("verified_query_id"),
            verified_query_version=authority_data.get("verified_query_version"),
            sql_fingerprint=authority_data.get("sql_fingerprint")),
        scope=dict(_get(data, "scope")),
        temporal=Temporal(requested=temporal_data.get("requested"), resolved=temporal_data.get("resolved"),
                           observed_as_of=temporal_data.get("observed_as_of"), granularity=temporal_data.get("granularity")),
        units=Units(unit=units_data.get("unit"), scale=units_data.get("scale"), basis=units_data.get("basis")),
        result=ResultEnvelope(
            kind=str(result_data["kind"]), columns=tuple(result_data.get("columns", ())),
            rows=tuple(dict(row) for row in result_data.get("rows", ())),
            total_rows=result_data.get("total_rows"), returned_rows=int(result_data.get("returned_rows", 0)),
            truncated=bool(result_data.get("truncated", False)), has_more=bool(result_data.get("has_more", False)),
            omission_reason=result_data.get("omission_reason")),
        facts=tuple(dict(fact) for fact in data.get("facts", ())),
        provenance=dict(data.get("provenance", {})),
        limitations=tuple(data.get("limitations", ())),
        coverage=dict(data["coverage"]) if data.get("coverage") is not None else None,
        semantic_contract=dict(data.get("semantic_contract", {})),
    )


@dataclass(frozen=True)
class StructuredOutputContract:
    name: str
    schema: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True)
class ToolResult:
    """The executor's answer to one ToolRequest, ready to hand back to a
    transport for replay."""

    call_id: str
    ok: bool
    content: str
    trace: dict[str, Any] = field(default_factory=dict)
    control: dict[str, Any] | None = None
    evidence: ToolEvidence | None = None

    def __post_init__(self) -> None:
        if not self.ok and self.evidence is not None:
            raise ValueError("ToolResult.evidence must be None when ok=False -- technical errors are not citeable evidence")


@dataclass(frozen=True)
class TranscriptItem:
    """One neutral entry in the conversation AnalystLoop keeps."""

    role: str  # "user" | "assistant"
    text: str | None = None
    tool_requests: list[ToolRequest] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    raw: Any = None


@dataclass(frozen=True)
class ModelRequest:
    """Everything a transport needs to make one model call."""

    system_prompt: str
    history: list[TranscriptItem]
    message: str
    tools: list[ToolSpec]
    output_contract: StructuredOutputContract | None = None


@dataclass(frozen=True)
class ModelResponse:
    """A transport's answer to one ModelRequest."""

    text: str
    tool_requests: list[ToolRequest] = field(default_factory=list)
    raw_items: Any = None
    usage: Usage = field(default_factory=Usage)
    structured_output: dict[str, Any] | None = None


class ModelTransport(Protocol):
    """One provider's translation of ModelRequest/ModelResponse to and from
    its wire protocol."""

    def complete(self, request: ModelRequest) -> ModelResponse: ...
