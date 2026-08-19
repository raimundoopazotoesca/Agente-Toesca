"""Provider-neutral contract between AnalystLoop and one model call.

F4 Stage 2's whole point: three reasoning loops (Chat Completions, OpenAI
Responses, Anthropic Messages) duplicated the same round-budget/synthesis
structure around three different wire protocols. This module is the seam --
everything on the AnalystLoop side of it is reasoning policy; everything on
the transport side of it is provider translation. Neither may leak into the
other (see analyst_loop.py's module docstring for the enforcement side of
that rule).

Deliberately NOT here, because AnalystLoop doesn't need them to do its job:
  - a `mode: investigation | synthesis` field on ModelRequest -- whether tools
    are offered *is* that distinction; encoding it twice would let the two
    disagree.
  - any SQL-specific type. `ToolSpec`/`ToolRequest`/`ToolResult` are shaped
    around what a generic function-calling tool looks like on the wire, not
    around run_sql specifically -- see ActionExecutor in analyst_loop.py for
    where SQL-specific behavior actually lives (outside both this module and
    AnalystLoop).

The one deliberately-imprecise field is `TranscriptItem.raw` / `ModelResponse
.raw_items`: opaque payload a transport needs echoed back verbatim on the next
call (OpenAI Responses' reasoning items, Anthropic's thinking/signature
blocks). AnalystLoop stores and replays it without ever inspecting it --
inspecting it would mean the loop understands provider wire formats, which is
exactly the coupling this module exists to remove.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from eval.benchmark.adapters.base import Usage


@dataclass(frozen=True)
class ToolSpec:
    """One callable tool, in the shape a function-calling API expects:
    name + description + JSON Schema parameters. Provider-agnostic --
    each transport re-serializes this to its own wire shape (OpenAI
    Chat Completions' {"type":"function","function":{...}}, Responses'
    flat {"type":"function","name":...}, Anthropic's {"name",
    "input_schema"})."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolRequest:
    """One tool invocation the model asked for, already decoded from
    whatever wire shape the provider used (OpenAI's JSON-string arguments,
    Anthropic's native dict `input`)."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The executor's answer to one ToolRequest, ready to hand back to a
    transport for replay. `content` is already serialized (the JSON string
    _format_tool_result produces today) -- AnalystLoop treats it as opaque
    text, never parses it."""

    call_id: str
    ok: bool
    content: str


@dataclass(frozen=True)
class TranscriptItem:
    """One neutral entry in the conversation AnalystLoop keeps. A transport
    reconstructs its own wire-format history from a sequence of these plus
    each item's `raw` (when present) on every call -- it never receives a
    pre-built provider-shaped message list from the loop.

    `raw` is the provider's own representation of this turn, when the
    transport that produced it needs it echoed back unmodified (reasoning
    items, thinking blocks). AnalystLoop never reads it, only stores and
    replays it. `raw is None` for turns the loop itself authored (the
    original user message, the synthesis instruction) -- those have no
    provider-side representation until a transport renders them.
    """

    role: str  # "user" | "assistant"
    text: str | None = None
    tool_requests: list[ToolRequest] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    raw: Any = None


@dataclass(frozen=True)
class ModelRequest:
    """Everything a transport needs to make one model call. `tools=[]` on
    the reserved synthesis round is what tells the transport to forbid new
    tool use (`tool_choice="none"` or equivalent) -- AnalystLoop expresses
    "no more investigation" this way instead of a separate mode flag, so
    there is exactly one place that decision is made."""

    system_prompt: str
    history: list[TranscriptItem]
    message: str
    tools: list[ToolSpec]


@dataclass(frozen=True)
class ModelResponse:
    """A transport's answer to one ModelRequest, decoded to the point
    AnalystLoop can act on it (is there text? are there tool requests?)
    without knowing which provider produced it.

    `raw_items` is the provider's own output representation for this turn,
    when replay requires it verbatim on the next call -- opaque to
    AnalystLoop, stored as the `raw` of the TranscriptItem this response
    becomes. `None`/`[]` for a transport whose protocol needs no such replay
    (Chat Completions reconstructs purely from tool_requests/tool_results).
    """

    text: str
    tool_requests: list[ToolRequest] = field(default_factory=list)
    raw_items: Any = None
    usage: Usage = field(default_factory=Usage)


class ModelTransport(Protocol):
    """One provider's translation of ModelRequest/ModelResponse to and from
    its wire protocol. A transport holds no reasoning-loop state -- no round
    counter, no budget, no notion of "investigation" vs "synthesis" beyond
    "did AnalystLoop hand me an empty `tools` list this call". Everything
    that decides *when* to call this, and *how many times*, is AnalystLoop's
    job, not the transport's.
    """

    def complete(self, request: ModelRequest) -> ModelResponse: ...
