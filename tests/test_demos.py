"""Smoke tests for the runnable demo scenarios.

Each demo loads the bundled offline fixture and runs the real public API; these
tests assert the fixture exists, the headline detections still fire, and every
scenario's main() runs to completion without raising.
"""
import importlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEMOS = os.path.join(REPO, "demos")
DATA = os.path.join(DEMOS, "data")

sys.path.insert(0, DEMOS)

SCENARIOS = [
    "01_osint_analyst_sweep",
    "02_sanctions_compliance",
    "03_port_security",
    "04_researcher_export",
    "05_gps_spoofing_ew",
    "06_fleet_network",
    "07_flag_hopping",
    "08_sts_correlation",
    "09_pattern_of_life",
    "10_cot_cop_export",
]


def test_fixtures_present():
    for fn in ("gulf_scenario.json", "gulf_zones.geojson", "gulf_sanctions.json"):
        assert os.path.exists(os.path.join(DATA, fn)), fn


def test_fixture_shape():
    recs = json.load(open(os.path.join(DATA, "gulf_scenario.json"), encoding="utf-8"))
    assert isinstance(recs, list) and len(recs) >= 40
    mmsis = {r["mmsi"] for r in recs}
    assert len(mmsis) == 7
    for r in recs[:5]:
        assert {"mmsi", "timestamp", "lat", "lon"} <= set(r)


def test_headline_detections_fire():
    from maritimeint.core import load_messages, analyze
    msgs = load_messages(os.path.join(DATA, "gulf_scenario.json"))
    counts = analyze(msgs)["finding_counts"]
    # the detections the demos narrate must stay non-empty
    for kind in ("ais_gap", "speed_jump", "loitering", "spoofing",
                 "dark_rendezvous", "gps_anomaly", "close_quarters"):
        assert counts[kind] >= 1, f"{kind} stopped firing on the demo fixture"


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_runs(name, capsys):
    mod = importlib.import_module(name)
    mod.main()  # must not raise
    out = capsys.readouterr().out
    assert "=" * 20 in out and len(out) > 100


def test_run_all_imports():
    mod = importlib.import_module("run_all")
    assert mod.SCENARIOS == SCENARIOS
