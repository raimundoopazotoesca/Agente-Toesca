"""Round B B0 provider probes. This module never opens benchmark data."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

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


def default_specs() -> tuple[ProviderSpec, ...]:
    """Explicit B0 roster; requested names are never silently substituted."""
    return (
        ProviderSpec("openai_sol", "gpt-5.6-sol", "OPENAI_API_KEY", "openai"),
        ProviderSpec("openai_terra", "gpt-5.6-terra", "OPENAI_API_KEY", "openai"),
        ProviderSpec("anthropic_sonnet", "claude-sonnet-5", "ANTHROPIC_API_KEY", "anthropic"),
        ProviderSpec("anthropic_opus", "claude-opus-5", "ANTHROPIC_API_KEY", "anthropic"),
        ProviderSpec("gemini", "gemini-3.1-pro-preview", "GEMINI_API_KEY", "gemini"),
        ProviderSpec("groq", "openai/gpt-oss-120b", "GROQ_API_KEY", "groq"),
        ProviderSpec("deepseek", "deepseek-v4-pro", "DEEPSEEK_API_KEY", "openai_compatible"),
        ProviderSpec("glm", "glm-5.2", "ZAI_API_KEY", "openai_compatible"),
        ProviderSpec("nvidia", "z-ai/glm-5.2", "NVIDIA_API_KEY", "openai_compatible"),
        ProviderSpec("alibaba_dashscope", "qwen3.8-max", "DASHSCOPE_API_KEY", "openai_compatible"),
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

    def __init__(self, env: Mapping[str, str] | None = None):
        self.env = dict(os.environ if env is None else env)

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
        result.classification = "adapter_work_needed"
        result.probes["credential"] = Probe("present")
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
