"""Version pin for Toesca Analyst Benchmark.

Snapshot + benchmark date form a single reproducible version. Neither is
refreshed silently: new data or a new date means v2, not an updated v1.
See docs/toesca-analyst-benchmark-v1-design.md section 4.
"""
from __future__ import annotations

BENCHMARK_VERSION = "v1"

# Frozen "today". Every relative period in a case ("este ano", "los ultimos
# 3 meses") resolves against this date, which is injected into the adapter.
# Without it, relative-period cases rot on their own.
BENCHMARK_TODAY = "2026-08-13"
