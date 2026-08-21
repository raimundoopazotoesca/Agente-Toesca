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

from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class ToolResult:
    """The executor's answer to one ToolRequest, ready to hand back to a
    transport for replay."""

    call_id: str
    ok: bool
    content: str
    trace: dict[str, Any] = field(default_factory=dict)
    control: dict[str, Any] | None = None


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


@dataclass(frozen=True)
class ModelResponse:
    """A transport's answer to one ModelRequest."""

    text: str
    tool_requests: list[ToolRequest] = field(default_factory=list)
    raw_items: Any = None
    usage: Usage = field(default_factory=Usage)


class ModelTransport(Protocol):
    """One provider's translation of ModelRequest/ModelResponse to and from
    its wire protocol."""

    def complete(self, request: ModelRequest) -> ModelResponse: ...
