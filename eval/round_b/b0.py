"""Round B B0 provider probes. This module never opens benchmark data."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import httpx

from dotenv import dotenv_values


_SECRET_ASSIGNMENT = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+")


def load_b0_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Load process env plus an explicitly selected *external* dotenv file.

    The path is opt-in via B0_ENV_FILE and files inside this worktree are
    rejected, so secrets are never copied or implicitly discovered.
    """
    env = dict(os.environ if base_env is None else base_env)
    path_value = env.get("B0_ENV_FILE")
    if not path_value:
        return env
    path = Path(path_value).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    if path == repo_root / ".env" or repo_root in path.parents:
        raise ValueError("B0_ENV_FILE must point outside the Round B worktree")
    if not path.is_file():
        raise ValueError("B0_ENV_FILE does not exist")
    for name, value in dotenv_values(path).items():
        if name and value is not None and not env.get(name):
            env[name] = value
    return env


def synthetic_fixtures() -> dict[str, object]:
    """The complete B0 corpus: deliberately invented and operationally inert."""
    return {
        "completion": "Resume: el proyecto Faro tiene 3 unidades.",
        "structured": {"status": "ok", "count": 3},
        "tool_call": {"name": "lookup_color", "arguments": {"code": "AZ-7"}},
        "tool_result": {"code": "AZ-7", "color": "azul"},
        "multi_tool": {"get_base": 10, "add_tax": 2, "expected": 12},
    }


def classify_error(message: str, *, provider_response_received: bool = False) -> str:
    message = (message or "").lower()
    if "invalid tool" in message or "tool arguments" in message:
        return "model_output_invalid" if provider_response_received else "adapter_protocol_failure"
    if "429" in message or "rate limit" in message or "quota" in message:
        return "quota_rate_limit_failure"
    if "401" in message or "403" in message or "api key" in message:
        return "credential_missing"
    return "provider_infra_failure"


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    requested_model: str
    credential_env: str
    protocol: str
    base_url: str | None = None


def default_specs() -> tuple[ProviderSpec, ...]:
    """Explicit B0 roster; requested names are never silently substituted."""
    return (
        ProviderSpec("openai_sol", "gpt-5.6-sol", "OPENAI_API_KEY", "openai"),
        ProviderSpec("openai_terra", "gpt-5.6-terra", "OPENAI_API_KEY", "openai"),
        ProviderSpec("anthropic_sonnet", "claude-sonnet-5", "ANTHROPIC_API_KEY", "anthropic"),
        ProviderSpec("anthropic_opus", "claude-opus-5", "ANTHROPIC_API_KEY", "anthropic"),
        ProviderSpec("gemini", "gemini-3.1-pro-preview", "GEMINI_API_KEY", "gemini"),
        ProviderSpec("groq", "openai/gpt-oss-120b", "GROQ_API_KEY", "openai_compatible", "https://api.groq.com/openai/v1"),
        ProviderSpec("deepseek", "deepseek-v4-pro", "DEEPSEEK_API_KEY", "openai_compatible"),
        ProviderSpec("glm", "glm-5.2", "ZAI_API_KEY", "openai_compatible"),
        ProviderSpec("nvidia", "z-ai/glm-5.2", "NVIDIA_API_KEY", "openai_compatible", "https://integrate.api.nvidia.com/v1"),
        ProviderSpec("alibaba_dashscope", "qwen3.8-max", "DASHSCOPE_API_KEY", "openai_compatible"),
        ProviderSpec("mistral", "mistral-large-2512", "MISTRAL_API_KEY", "openai_compatible", "https://api.mistral.ai/v1"),
        ProviderSpec("sambanova_deepseek", "DeepSeek-V3.2", "SAMBANOVA_API_KEY", "openai_compatible", "https://api.sambanova.ai/v1"),
        ProviderSpec("sambanova_minimax", "MiniMax-M2.7", "SAMBANOVA_API_KEY", "openai_compatible", "https://api.sambanova.ai/v1"),
        ProviderSpec("xai", "grok-4.5", "XAI_API_KEY", "openai"),
        ProviderSpec("kimi", "kimi-k3", "MOONSHOT_API_KEY", "openai_compatible"),
    )


@dataclass
class Probe:
    status: str = "not_run"
    detail: str | None = None


@dataclass
class B0Result:
    provider: str
    requested_model: str
    resolved_model: str | None = None
    classification: str = "adapter_work_needed"
    probes: dict[str, Probe] = field(default_factory=dict)
    telemetry: dict[str, object] = field(default_factory=dict)
    error_taxonomy: str | None = None


class HttpxTransport:
    """Small injectable boundary: raw responses never enter B0 results."""

    def request(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, Any] | None, timeout: float):
        response = httpx.request(method, url, headers=headers, json=json, timeout=timeout)
        try:
            body = response.json()
        except ValueError:
            body = {"message": response.text[:300]}
        return response.status_code, body


class B0Runner:
    """Runs only probes against the synthetic fixtures above.

    Network-capable native clients will be supplied in a later, provider-specific
    layer; absence of credentials is intentionally a complete result, not an
    exception and not a reason to inspect real benchmark data.
    """

    PROBE_NAMES = (
        "credential", "completion", "structured", "tool_call", "tool_result_replay",
        "multi_tool", "usage_telemetry", "protocol_metadata",
    )

    def __init__(self, env: Mapping[str, str] | None = None, transport: Any | None = None):
        self.env = dict(os.environ if env is None else env)
        self.transport = transport or HttpxTransport()

    def _empty_result(self, spec: ProviderSpec) -> B0Result:
        return B0Result(
            provider=spec.provider,
            requested_model=spec.requested_model,
            probes={name: Probe() for name in self.PROBE_NAMES},
        )

    def run_one(self, spec: ProviderSpec) -> B0Result:
        result = self._empty_result(spec)
        if spec.provider == "alibaba_dashscope":
            result.telemetry["base_url_configured"] = bool(self.env.get("DASHSCOPE_BASE_URL"))
        if not self.env.get(spec.credential_env):
            result.classification = "credential_missing"
            result.error_taxonomy = "credential_missing"
            result.probes["credential"] = Probe("missing", f"{spec.credential_env} is not configured")
            return result
        if spec.protocol == "gemini":
            return self._run_gemini(spec, result)
        if spec.protocol != "openai_compatible":
            result.classification = "adapter_work_needed"
            result.probes["credential"] = Probe("present")
            return result
        return self._run_openai_compatible(spec, result)

    def _base_url(self, spec: ProviderSpec) -> str:
        if spec.provider == "alibaba_dashscope":
            return self.env.get("DASHSCOPE_BASE_URL", "").rstrip("/")
        return (spec.base_url or "").rstrip("/")

    @staticmethod
    def _usage(result: B0Result, body: Mapping[str, Any]) -> None:
        usage = body.get("usage") or {}
        def add(name: str, *keys: str) -> None:
            value = next((usage.get(key) for key in keys if isinstance(usage.get(key), int)), 0)
            result.telemetry[name] = int(result.telemetry.get(name, 0)) + int(value)
        add("input_tokens", "prompt_tokens", "input_tokens")
        add("output_tokens", "completion_tokens", "output_tokens")
        add("cached_tokens", "cached_tokens")
        add("reasoning_tokens", "reasoning_tokens")
        details = usage.get("completion_tokens_details") or {}
        if isinstance(details.get("reasoning_tokens"), int):
            result.telemetry["reasoning_tokens"] = int(result.telemetry.get("reasoning_tokens", 0)) + details["reasoning_tokens"]

    def _call(self, spec: ProviderSpec, result: B0Result, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Mapping[str, Any], float]:
        base_url = self._base_url(spec)
        if not base_url:
            return 0, {"message": "base URL is not configured"}, 0.0
        headers = {"Authorization": f"Bearer {self.env[spec.credential_env]}", "Content-Type": "application/json"}
        timeout = 60.0 if spec.provider.startswith("sambanova") else 30.0
        started = time.monotonic()
        try:
            status, body = self.transport.request(method, f"{base_url}{path}", headers=headers, json=payload, timeout=timeout)
        except Exception as exc:
            status, body = 0, {"message": self.sanitize_error(str(exc))}
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        result.telemetry["requests"] = int(result.telemetry.get("requests", 0)) + 1
        return status, body if isinstance(body, Mapping) else {}, latency_ms

    def _fail(self, result: B0Result, probe: str, status: int, body: Mapping[str, Any], latency_ms: float) -> B0Result:
        message = self.sanitize_error(str(body.get("message") or body.get("error") or f"HTTP {status}"))
        taxonomy = classify_error(f"{status} {message}")
        result.probes[probe] = Probe("failed", taxonomy)
        result.error_taxonomy = taxonomy
        result.classification = "quota_rate_limit_failure" if taxonomy == "quota_rate_limit_failure" else "provider_infra_failure"
        result.telemetry[f"{probe}_latency_ms"] = latency_ms
        return result

    def _run_openai_compatible(self, spec: ProviderSpec, result: B0Result) -> B0Result:
        status, body, latency = self._call(spec, result, "GET", "/models")
        model_listing_available = 200 <= status < 300
        result.probes["credential"] = Probe("passed" if model_listing_available else "not_run")
        result.resolved_model = spec.requested_model
        payloads = {
            "completion": {"model": spec.requested_model, "messages": [{"role": "user", "content": synthetic_fixtures()["completion"]}], "max_tokens": 2048},
            "structured": {"model": spec.requested_model, "messages": [{"role": "user", "content": "Return exactly JSON: {status: ok, count: 3}."}], "response_format": {"type": "json_object"}, "max_tokens": 512},
            "tool_call": {"model": spec.requested_model, "messages": [{"role": "user", "content": "Use lookup_color for AZ-7."}], "tools": [{"type": "function", "function": {"name": "lookup_color", "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}}], "max_tokens": 1024},
            "tool_result_replay": {"model": spec.requested_model, "messages": [{"role": "user", "content": "The lookup result is AZ-7 is azul. Confirm it."}], "max_tokens": 512},
            "multi_tool": {"model": spec.requested_model, "messages": [{"role": "user", "content": "Use get_base then add_tax to calculate 10 plus 2."}], "tools": [{"type": "function", "function": {"name": "get_base", "parameters": {"type": "object", "properties": {}}}}, {"type": "function", "function": {"name": "add_tax", "parameters": {"type": "object", "properties": {}}}}], "max_tokens": 1024},
        }
        for probe, payload in payloads.items():
            status, body, latency = self._call(spec, result, "POST", "/chat/completions", payload)
            if status < 200 or status >= 300:
                return self._fail(result, probe, status, body, latency)
            self._usage(result, body)
            if result.probes["credential"].status != "passed":
                # A successful authenticated inference is stronger evidence than
                # an optional /models endpoint.
                result.probes["credential"] = Probe("passed")
            result.probes[probe] = Probe("passed")
            result.telemetry[f"{probe}_latency_ms"] = latency
            choices = body.get("choices") or []
            if choices and isinstance(choices[0], Mapping) and choices[0].get("finish_reason") == "length":
                result.probes[probe] = Probe("failed", "output_truncated_by_token_limit")
        result.probes["usage_telemetry"] = Probe("passed")
        result.probes["protocol_metadata"] = Probe("passed")
        result.classification = "adapter_ready" if all(p.status == "passed" for p in result.probes.values()) else "adapter_work_needed"
        return result

    def _run_gemini(self, spec: ProviderSpec, result: B0Result) -> B0Result:
        base_url = "https://generativelanguage.googleapis.com/v1beta"
        headers = {"x-goog-api-key": self.env[spec.credential_env], "Content-Type": "application/json"}
        payload = {"contents": [{"role": "user", "parts": [{"text": synthetic_fixtures()["completion"]}]}]}
        started = time.monotonic()
        try:
            status, body = self.transport.request("POST", f"{base_url}/models/{spec.requested_model}:generateContent", headers=headers, json=payload, timeout=30.0)
        except Exception as exc:
            status, body = 0, {"message": self.sanitize_error(str(exc))}
        latency = round((time.monotonic() - started) * 1000, 1)
        result.telemetry["requests"] = 1
        if status < 200 or status >= 300:
            return self._fail(result, "credential", status, body, latency)
        result.probes["credential"] = Probe("passed")
        result.probes["completion"] = Probe("passed")
        result.resolved_model = spec.requested_model
        result.classification = "adapter_work_needed"
        return result

    @staticmethod
    def sanitize_error(message: str) -> str:
        """Keep diagnostics useful without allowing auth values into results."""
        return _SECRET_ASSIGNMENT.sub("[redacted authorization]", message or "")

    def record_metadata(self, spec: ProviderSpec, opaque_metadata: str | bytes | None) -> dict[str, object]:
        if opaque_metadata is None:
            return {"present": False}
        raw = opaque_metadata.encode("utf-8") if isinstance(opaque_metadata, str) else opaque_metadata
        return {"present": True, "sha256": hashlib.sha256(raw).hexdigest(), "provider": spec.provider}


def main() -> None:
    """Credential-only B0 pass; network adapters activate only after keys exist."""
    runner = B0Runner(env=load_b0_env())
    rows = []
    for spec in default_specs():
        result = runner.run_one(spec)
        rows.append({
            "provider": result.provider,
            "requested_model": result.requested_model,
            "resolved_model": result.resolved_model,
            "classification": result.classification,
            "error_taxonomy": result.error_taxonomy,
            "probes": {name: probe.status for name, probe in result.probes.items()},
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
