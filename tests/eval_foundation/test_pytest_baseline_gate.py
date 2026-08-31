"""Tests for the baseline-aware pytest gating infrastructure (Eval Foundation
Step 0, Task 1).

Two layers:

1. Unit tests against `evaluate_run` directly, covering every classification
   in the plan's Global constraints / Task 1 execution amendments.
2. Round-trip tests that run a real, isolated pytest subprocess with
   `tools.eval.pytest_nodeid_reporter` registered, to prove the plugin
   actually emits the exact records `evaluate_run` depends on (parametrized
   IDs, class-method IDs, setup/teardown errors, skip, xfail, collection
   failure) before that data is trusted for gating.

No test here touches the system under test or calls an LLM/judge — this
suite only runs pytest against small, throwaway fixture files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.eval.pytest_baseline_gate import (
    REQUIRED_BASE_COMMIT,
    BaselineGateResult,
    ManifestError,
    evaluate_run,
    load_allowlist,
    load_historical,
)
from tools.eval.pytest_nodeid_reporter import NodeIdReporterPlugin

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rec(nodeid: str, phase: str, outcome: str, wasxfail=None) -> dict:
    return {"nodeid": nodeid, "phase": phase, "outcome": outcome, "wasxfail": wasxfail}


def _historical(failure_ids, base_commit=REQUIRED_BASE_COMMIT, skip_ids=None) -> dict:
    return {
        "base_commit": base_commit,
        "command": "python -X utf8 -m pytest tests --junitxml=artifacts/pytest-d986996.xml",
        "summary": {"failed": len(failure_ids), "passed": 1341, "skipped": 9, "xfailed": 1},
        "failure_ids": list(failure_ids),
        "skip_ids": skip_ids or [],
    }


def _run_pytest_with_reporter(tmp_path: Path, test_source: str, report_name: str = "report.json"):
    """Run a real, isolated pytest subprocess with the nodeid reporter plugin
    registered, against a single throwaway test file under ``tmp_path``.

    ``tmp_path`` is used both as the target directory and the pytest cwd, so
    the run never picks up this repo's own ``pytest.ini`` (rootdir discovery
    walks up from ``tmp_path``, which sits under the OS temp dir).
    """
    test_file = tmp_path / "test_fixture_module.py"
    test_file.write_text(test_source, encoding="utf-8")
    report_path = tmp_path / report_name

    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(REPO_ROOT) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            ".",
            "-p",
            "tools.eval.pytest_nodeid_reporter",
            f"--nodeid-report={report_path}",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert report_path.exists(), (
        f"nodeid report was not written; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return proc, data


def _records_by_id(data: dict) -> dict:
    by_id: dict = {}
    for rec in data["records"]:
        by_id.setdefault(rec["nodeid"], {})[rec["phase"]] = rec
    return by_id


# ---------------------------------------------------------------------------
# evaluate_run: core semantics from the old illustrative snippet, preserved
# under the authoritative interface.
# ---------------------------------------------------------------------------


def test_new_failure_blocks_even_if_total_failure_count_drops():
    # Baseline had two failures; the current run only has one failure left,
    # but it's a brand-new ID never seen before -> must still block.
    historical = _historical(["old_a", "old_b"])
    active_allowlist = ["old_a", "old_b"]
    records = [
        _rec("old_a", "setup", "passed"),
        _rec("old_a", "call", "passed"),
        _rec("old_a", "teardown", "passed"),
        _rec("old_b", "setup", "passed"),
        _rec("old_b", "call", "passed"),
        _rec("old_b", "teardown", "passed"),
        _rec("new_c", "setup", "passed"),
        _rec("new_c", "call", "failed"),
        _rec("new_c", "teardown", "passed"),
    ]
    collected_ids = ["old_a", "old_b", "new_c"]

    result = evaluate_run(records, historical, active_allowlist, collected_ids)

    assert result.new_failure_ids == ["new_c"]
    assert result.exit_code == 1


def test_resolved_baseline_id_is_visible_but_not_a_failure():
    # old_a was on the historical baseline but has already been removed from
    # the active allowlist by an earlier, separately reviewed fix. It now
    # passes -> report it as resolved, but it must not block by itself.
    historical = _historical(["old_a"])
    active_allowlist: list[str] = []
    records = [
        _rec("old_a", "setup", "passed"),
        _rec("old_a", "call", "passed"),
        _rec("old_a", "teardown", "passed"),
    ]
    collected_ids = ["old_a"]

    result = evaluate_run(records, historical, active_allowlist, collected_ids)

    assert result.resolved_baseline_ids == ["old_a"]
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# evaluate_run: every classification in the Task 1 execution amendments.
# ---------------------------------------------------------------------------


def test_allowed_failure_stays_visible_and_does_not_block():
    historical = _historical(["known_a"])
    records = [_rec("known_a", "setup", "passed"), _rec("known_a", "call", "failed")]
    result = evaluate_run(records, historical, ["known_a"], ["known_a"])

    assert result.allowed_failure_ids == ["known_a"]
    assert result.exit_code == 0


def test_allowed_failure_passes_but_allowlist_unchanged_is_stale_and_blocks():
    # "allowed failure passes but allowlist unchanged": the fix landed in
    # code but nobody shrank the allowlist in the same change -> must block.
    historical = _historical(["known_a"])
    records = [_rec("known_a", "setup", "passed"), _rec("known_a", "call", "passed")]
    result = evaluate_run(records, historical, ["known_a"], ["known_a"])

    assert result.stale_pass_ids == ["known_a"]
    assert result.exit_code == 1


@pytest.mark.parametrize(
    "regression_records,expected_state",
    [
        ([_rec("known_a", "setup", "skipped")], "skipped"),
        ([_rec("known_a", "call", "skipped", wasxfail="regressed")], "xfail"),
        ([_rec("known_a", "setup", "failed")], "error"),
        ([_rec("known_a", "setup", "passed"), _rec("known_a", "teardown", "failed")], "error"),
    ],
    ids=["skip", "xfail", "setup-error", "teardown-error"],
)
def test_allowed_failure_regresses_to_prohibited_state_blocks(regression_records, expected_state):
    # "allowed failure regresses to xfail/skip/error/not-collected": none of
    # these count as resolved; all of them must block.
    historical = _historical(["known_a"])
    result = evaluate_run(regression_records, historical, ["known_a"], ["known_a"])

    assert result.prohibited_state_ids == {"known_a": expected_state}
    assert result.exit_code == 1


def test_allowlist_id_not_collected_blocks():
    historical = _historical(["known_a", "known_b"])
    records = [_rec("known_b", "setup", "passed"), _rec("known_b", "call", "failed")]
    result = evaluate_run(records, historical, ["known_a", "known_b"], ["known_b"])

    assert result.not_collected_ids == ["known_a"]
    assert result.allowed_failure_ids == ["known_b"]
    assert result.exit_code == 1


def test_collection_error_blocks_unconditionally_even_with_empty_allowlist():
    historical = _historical([])
    records = [_rec("tests/test_broken.py", "collect", "failed")]
    result = evaluate_run(records, historical, [], [])

    assert result.collection_errors == ["tests/test_broken.py"]
    assert result.exit_code == 1


def test_internal_error_blocks_unconditionally():
    historical = _historical(["known_a"])
    records = [
        _rec("known_a", "setup", "passed"),
        _rec("known_a", "call", "failed"),
        _rec("<internal>", "internal", "failed"),
    ]
    result = evaluate_run(records, historical, ["known_a"], ["known_a"])

    # known_a is a legitimate allowed failure...
    assert result.allowed_failure_ids == ["known_a"]
    # ...but the internal error still blocks the whole run.
    assert result.internal_errors == ["<internal>"]
    assert result.exit_code == 1


def test_new_call_failed_id_not_on_allowlist_blocks():
    historical = _historical(["known_a"])
    records = [
        _rec("known_a", "setup", "passed"),
        _rec("known_a", "call", "failed"),
        _rec("brand_new", "setup", "passed"),
        _rec("brand_new", "call", "failed"),
    ]
    result = evaluate_run(
        records, historical, ["known_a"], ["known_a", "brand_new"]
    )

    assert result.new_failure_ids == ["brand_new"]
    assert result.allowed_failure_ids == ["known_a"]
    assert result.exit_code == 1


def test_clean_run_with_no_active_allowlist_is_not_blocking():
    historical = _historical([])
    records = [_rec("passing_test", "setup", "passed"), _rec("passing_test", "call", "passed")]
    result = evaluate_run(records, historical, [], ["passing_test"])

    assert result == BaselineGateResult()
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Manifest validation (load_historical / load_allowlist)
# ---------------------------------------------------------------------------


def test_load_historical_rejects_wrong_base_commit(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(_historical(["a"], base_commit="deadbeef")), encoding="utf-8")
    with pytest.raises(ManifestError, match="base_commit"):
        load_historical(path)


def test_load_historical_accepts_correct_base_commit(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(_historical(["b", "a"])), encoding="utf-8")
    historical = load_historical(path)
    assert historical["failure_ids"] == ["a", "b"]  # sorted
    assert historical["base_commit"] == REQUIRED_BASE_COMMIT


@pytest.mark.parametrize(
    "failure_ids",
    [["a", "a"], ["a", ""], ["a", 1]],
    ids=["duplicate", "empty", "non-string"],
)
def test_load_historical_rejects_invalid_ids(tmp_path, failure_ids):
    path = tmp_path / "baseline.json"
    payload = _historical([])
    payload["failure_ids"] = failure_ids
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_historical(path)


def test_load_historical_requires_command_and_summary(tmp_path):
    payload = _historical(["a"])
    del payload["command"]
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestError, match="command"):
        load_historical(path)


def test_load_allowlist_accepts_list_form(tmp_path):
    path = tmp_path / "allow.json"
    path.write_text(json.dumps(["b", "a"]), encoding="utf-8")
    assert load_allowlist(path) == ["a", "b"]


def test_load_allowlist_accepts_object_form(tmp_path):
    path = tmp_path / "allow.json"
    path.write_text(json.dumps({"failure_ids": ["b", "a"]}), encoding="utf-8")
    assert load_allowlist(path) == ["a", "b"]


def test_load_allowlist_rejects_duplicates(tmp_path):
    path = tmp_path / "allow.json"
    path.write_text(json.dumps(["a", "a"]), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_allowlist(path)


# ---------------------------------------------------------------------------
# Plugin round-trip: prove the reporter's JSON exactly matches what pytest
# actually did, for every node-ID shape and outcome we rely on for gating.
# ---------------------------------------------------------------------------


def test_plugin_round_trip_parametrized_and_class_method_nodeids(tmp_path):
    source = """
import pytest

@pytest.mark.parametrize("value", [1, 2])
def test_param(value):
    assert value in (1, 2)

@pytest.mark.parametrize("value", [1, 2])
def test_param_fails_on_two(value):
    assert value == 1

class TestGroup:
    def test_method_passes(self):
        assert True

    def test_method_fails(self):
        assert False
"""
    proc, data = _run_pytest_with_reporter(tmp_path, source)
    by_id = _records_by_id(data)

    expected_ids = {
        "test_fixture_module.py::test_param[1]",
        "test_fixture_module.py::test_param[2]",
        "test_fixture_module.py::test_param_fails_on_two[1]",
        "test_fixture_module.py::test_param_fails_on_two[2]",
        "test_fixture_module.py::TestGroup::test_method_passes",
        "test_fixture_module.py::TestGroup::test_method_fails",
    }
    assert expected_ids.issubset(set(data["collected_ids"]))
    assert expected_ids.issubset(set(by_id))

    assert by_id["test_fixture_module.py::test_param[1]"]["call"]["outcome"] == "passed"
    assert by_id["test_fixture_module.py::test_param[2]"]["call"]["outcome"] == "passed"
    assert (
        by_id["test_fixture_module.py::test_param_fails_on_two[1]"]["call"]["outcome"] == "passed"
    )
    assert (
        by_id["test_fixture_module.py::test_param_fails_on_two[2]"]["call"]["outcome"] == "failed"
    )
    assert by_id["test_fixture_module.py::TestGroup::test_method_passes"]["call"]["outcome"] == "passed"
    assert by_id["test_fixture_module.py::TestGroup::test_method_fails"]["call"]["outcome"] == "failed"

    assert proc.returncode == 1  # some tests failed


def test_plugin_round_trip_skip_and_xfail(tmp_path):
    source = """
import pytest

@pytest.mark.skip(reason="demo skip")
def test_skipped():
    assert False

@pytest.mark.xfail(reason="demo xfail", strict=False)
def test_xfail_expected():
    assert False

@pytest.mark.xfail(reason="demo xpass", strict=False)
def test_xfail_unexpected_pass():
    assert True
"""
    proc, data = _run_pytest_with_reporter(tmp_path, source)
    by_id = _records_by_id(data)

    skipped = by_id["test_fixture_module.py::test_skipped"]
    assert skipped["setup"]["outcome"] == "skipped"
    assert skipped["setup"]["wasxfail"] is None

    xfail_expected = by_id["test_fixture_module.py::test_xfail_expected"]
    assert xfail_expected["call"]["outcome"] == "skipped"
    assert xfail_expected["call"]["wasxfail"]

    xpass = by_id["test_fixture_module.py::test_xfail_unexpected_pass"]
    assert xpass["call"]["outcome"] == "passed"
    assert xpass["call"]["wasxfail"]

    assert proc.returncode == 0  # skip/xfail/xpass(non-strict) are all "ok"


def test_plugin_round_trip_setup_and_teardown_errors(tmp_path):
    source = """
import pytest

@pytest.fixture
def broken_setup():
    raise RuntimeError("setup boom")
    yield

def test_setup_error(broken_setup):
    assert True

@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown boom")

def test_teardown_error(broken_teardown):
    assert True
"""
    proc, data = _run_pytest_with_reporter(tmp_path, source)
    by_id = _records_by_id(data)

    setup_error = by_id["test_fixture_module.py::test_setup_error"]
    assert setup_error["setup"]["outcome"] == "failed"
    assert "call" not in setup_error

    teardown_error = by_id["test_fixture_module.py::test_teardown_error"]
    assert teardown_error["call"]["outcome"] == "passed"
    assert teardown_error["teardown"]["outcome"] == "failed"

    assert proc.returncode == 1


def test_plugin_round_trip_collection_failure(tmp_path):
    source = "import this_module_does_not_exist_xyz123\n\ndef test_never_runs():\n    assert True\n"
    proc, data = _run_pytest_with_reporter(tmp_path, source)

    assert data["collection_errors"], "expected a recorded collection error"
    assert any(rec["phase"] == "collect" and rec["outcome"] == "failed" for rec in data["records"])
    assert data["collected_ids"] == []
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# End-to-end: real plugin output fed straight into evaluate_run, proving the
# whole pipeline (not just each half in isolation).
# ---------------------------------------------------------------------------


def test_end_to_end_new_failure_from_real_plugin_output_blocks(tmp_path):
    source = """
def test_ok():
    assert True

def test_regresses():
    assert False
"""
    _, data = _run_pytest_with_reporter(tmp_path, source)
    historical = _historical([])
    result = evaluate_run(
        records=data["records"],
        historical=historical,
        active_allowlist=[],
        collected_ids=data["collected_ids"],
    )
    assert result.new_failure_ids == ["test_fixture_module.py::test_regresses"]
    assert result.exit_code == 1


def test_end_to_end_allowed_failure_from_real_plugin_output_does_not_block(tmp_path):
    source = """
def test_known_failure():
    assert False
"""
    _, data = _run_pytest_with_reporter(tmp_path, source)
    node_id = "test_fixture_module.py::test_known_failure"
    historical = _historical([node_id])
    result = evaluate_run(
        records=data["records"],
        historical=historical,
        active_allowlist=[node_id],
        collected_ids=data["collected_ids"],
    )
    assert result.allowed_failure_ids == [node_id]
    assert result.exit_code == 0


def test_plugin_internal_error_record_shape_matches_evaluate_run_expectations():
    # Triggering a genuine pytest_internalerror deterministically in-process
    # is unreliable across pytest versions; instead prove the plugin method
    # itself produces the exact record shape evaluate_run consumes.
    plugin = NodeIdReporterPlugin(Path("unused.json"))
    plugin.pytest_internalerror(excrepr="boom: something internal broke")

    assert plugin.records == [
        {"nodeid": "<internal>", "phase": "internal", "outcome": "failed", "wasxfail": None}
    ]
    assert plugin.internal_errors == [{"detail": "boom: something internal broke"}]

    result = evaluate_run(plugin.records, _historical([]), [], [])
    assert result.internal_errors == ["<internal>"]
    assert result.exit_code == 1
