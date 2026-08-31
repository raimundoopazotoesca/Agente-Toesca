"""Pytest plugin: exact node-ID/phase/outcome reporting for baseline gating.

Registers a `--nodeid-report <path>` CLI option. When given, writes a JSON
file at session finish containing:

- ``records``: one entry per (nodeid, phase) pytest test-report, where
  ``phase`` is ``"setup" | "call" | "teardown"`` for ordinary tests, plus two
  synthetic phases used to surface infrastructure problems in the same
  stream that `tools.eval.pytest_baseline_gate.evaluate_run` consumes:
  ``"collect"`` for collection failures and ``"internal"`` for pytest
  internal errors. Each record carries the exact ``report.nodeid``,
  ``outcome``, and ``wasxfail`` (``None`` unless xfail machinery set it).
- ``collected_ids``: the full list of node IDs pytest actually collected
  into runnable items (i.e. ``[item.nodeid for item in items]``).
- ``collection_errors`` / ``internal_errors``: human-readable detail for the
  same synthetic records above (long reprs), for the JUnit/CI artifact —
  not consumed by ``evaluate_run`` directly.
- ``exit_status``: pytest's own session exit code.

JUnit XML remains the human/GitHub-facing artifact; this JSON is the
authoritative machine input for gating.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("nodeid-report")
    group.addoption(
        "--nodeid-report",
        action="store",
        default=None,
        dest="nodeid_report_path",
        help="Path to write the JSON node-ID/phase/outcome report used by "
        "tools.eval.pytest_baseline_gate.",
    )


class NodeIdReporterPlugin:
    """Collects exact node-ID/phase/outcome data for one pytest session."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.records: list[dict[str, Any]] = []
        self.collected_ids: list[str] = []
        self.collection_errors: list[dict[str, Any]] = []
        self.internal_errors: list[dict[str, Any]] = []

    def pytest_collection_modifyitems(self, items: list[Any]) -> None:
        self.collected_ids = [item.nodeid for item in items]

    def pytest_collectreport(self, report: Any) -> None:
        if not report.failed:
            return
        detail = str(report.longrepr) if report.longrepr else None
        self.collection_errors.append({"nodeid": report.nodeid, "longrepr": detail})
        self.records.append(
            {
                "nodeid": report.nodeid,
                "phase": "collect",
                "outcome": "failed",
                "wasxfail": None,
            }
        )

    def pytest_internalerror(self, excrepr: Any) -> None:
        detail = str(excrepr)
        self.internal_errors.append({"detail": detail})
        self.records.append(
            {
                "nodeid": "<internal>",
                "phase": "internal",
                "outcome": "failed",
                "wasxfail": None,
            }
        )

    def pytest_runtest_logreport(self, report: Any) -> None:
        self.records.append(
            {
                "nodeid": report.nodeid,
                "phase": report.when,
                "outcome": report.outcome,
                "wasxfail": getattr(report, "wasxfail", None),
            }
        )

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        data = {
            "collected_ids": self.collected_ids,
            "records": self.records,
            "collection_errors": self.collection_errors,
            "internal_errors": self.internal_errors,
            "exit_status": int(exitstatus),
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )


def pytest_configure(config: Any) -> None:
    path = config.getoption("nodeid_report_path")
    if not path:
        return
    plugin = NodeIdReporterPlugin(Path(path))
    config.pluginmanager.register(plugin, "nodeid_reporter_instance")
    config._nodeid_reporter_plugin = plugin  # exposed for in-process tests
