from __future__ import annotations

from eval.round_b.b0 import B0Runner, ProviderSpec, classify_error, default_specs, load_b0_env, synthetic_fixtures


class _SyntheticTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, url, *, headers=None, json=None, timeout=None):
        self.calls.append((method, url, headers, json, timeout))
        if method == "GET":
            return 200, {"data": [{"id": "demo-model"}]}
        return 200, {
            "model": "demo-model",
            "choices": [{"finish_reason": "stop", "message": {"content": '{\"status\": \"ok\", \"count\": 3}'}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }


class _ModelsUnavailableTransport(_SyntheticTransport):
    def request(self, method, url, *, headers=None, json=None, timeout=None):
        if method == "GET":
            return 404, {"message": "models endpoint unavailable"}
        return super().request(method, url, headers=headers, json=json, timeout=timeout)


def test_synthetic_fixtures_are_generic_and_contain_all_probe_inputs():
    fixtures = synthetic_fixtures()
    assert set(fixtures) == {"completion", "structured", "tool_call", "tool_result", "multi_tool"}
    rendered = repr(fixtures).lower()
    assert "faro" in rendered
    assert "az-7" in rendered
    assert "toesca" not in rendered


def test_classify_invalid_model_tool_arguments_as_model_output_not_adapter_failure():
    assert classify_error("invalid tool arguments", provider_response_received=True) == "model_output_invalid"


def test_runner_marks_missing_credential_without_attempting_network():
    spec = ProviderSpec("demo", "demo-model", "ABSENT_B0_TEST_KEY", "openai")
    result = B0Runner(env={}).run_one(spec)
    assert result.classification == "credential_missing"
    assert result.probes["credential"].status == "missing"
    assert result.requested_model == "demo-model"


def test_metadata_is_hashed_without_persisting_opaque_value():
    spec = ProviderSpec("demo", "demo-model", "ABSENT_B0_TEST_KEY", "openai")
    result = B0Runner(env={}).record_metadata(spec, "opaque-signature")
    assert result["present"] is True
    assert "opaque-signature" not in repr(result)
    assert len(result["sha256"]) == 64


def test_default_catalog_preserves_requested_models_without_substitution():
    specs = {spec.provider: spec.requested_model for spec in default_specs()}
    assert specs["alibaba_dashscope"] == "qwen3.8-max"
    assert specs["kimi"] == "kimi-k3"
    assert specs["groq"] == "openai/gpt-oss-120b"
    assert specs["nvidia"] == "z-ai/glm-5.2"
    assert specs["alibaba_dashscope"] == "qwen3.8-max"


def test_dashscope_base_url_is_recorded_only_as_a_boolean():
    result = B0Runner(env={"DASHSCOPE_BASE_URL": "https://private.example"}).run_one(
        ProviderSpec("alibaba_dashscope", "qwen3.8-max", "DASHSCOPE_API_KEY", "openai_compatible")
    )
    assert result.telemetry["base_url_configured"] is True
    assert "private.example" not in repr(result)


def test_external_env_file_is_loaded_without_exposing_its_secret(tmp_path):
    secret = "do-not-report-this-value"
    env_file = tmp_path / "local.env"
    env_file.write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    env = load_b0_env({"B0_ENV_FILE": str(env_file)})
    result = B0Runner(env=env).run_one(ProviderSpec("demo", "demo-model", "OPENAI_API_KEY", "openai"))
    assert result.probes["credential"].status == "present"
    assert secret not in repr(result)


def test_http_error_is_sanitized_of_authorization_header():
    secret = "Bearer private-token"
    result = B0Runner(env={}).sanitize_error(f"401 Authorization: {secret}")
    assert "private-token" not in result
    assert "Authorization" not in result


def test_openai_compatible_b0_runs_synthetic_probes_and_never_persists_key():
    secret = "private-test-token"
    transport = _SyntheticTransport()
    result = B0Runner(env={"DEMO_KEY": secret}, transport=transport).run_one(
        ProviderSpec("demo", "demo-model", "DEMO_KEY", "openai_compatible", "https://demo.invalid/v1")
    )
    assert result.probes["credential"].status == "passed"
    assert result.probes["completion"].status == "passed"
    assert result.probes["usage_telemetry"].status == "passed"
    assert result.telemetry["input_tokens"] == 20
    assert result.telemetry["output_tokens"] == 10
    assert secret not in repr(result)


def test_completion_can_establish_b0_evidence_when_models_endpoint_is_unavailable():
    result = B0Runner(env={"DEMO_KEY": "secret"}, transport=_ModelsUnavailableTransport()).run_one(
        ProviderSpec("demo", "demo-model", "DEMO_KEY", "openai_compatible", "https://demo.invalid/v1")
    )
    assert result.probes["credential"].status == "passed"
    assert result.probes["completion"].status == "passed"
