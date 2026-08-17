from pathlib import Path

from eval.round_b.runner import build_run_manifest, estimate_cost, validate_mini_dev


ROOT = Path(__file__).resolve().parents[2]


def test_validate_mini_dev_uses_canonical_content_identity_not_file_bytes():
    checked = validate_mini_dev(ROOT / "eval/round_b/mini_dev_v1.yaml")
    assert checked["canonical_manifest_sha256"] == "dc4d8912986ac99e9a08853d55fa19668220032e41a89944c05d1cfcc573b976"
    assert checked["case_count"] == 15
    assert checked["turn_count"] == 25


def test_manifest_pins_b1_and_committed_code_sha():
    manifest = build_run_manifest("abc123", "2026-08-17")
    assert manifest["track"] == "B"
    assert manifest["mini_dev"]["canonical_manifest_sha256"].startswith("dc4d8912")
    assert manifest["code_commit_sha"] == "abc123"
    assert manifest["inference_profile"] == "B1_STANDARD"
    assert manifest["judge_status"] == "not_scored_yet"


def test_cost_is_unknown_without_price_or_usage_and_known_for_groq():
    assert estimate_cost("nvidia", "z-ai/glm-5.2", 10, 2, 0) is None
    assert estimate_cost("groq", "openai/gpt-oss-120b", 1_000_000, 1_000_000, 0) == {"currency": "USD", "amount": 0.75}
