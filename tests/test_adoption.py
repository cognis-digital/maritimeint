"""Adoption features: CSV ingest, the --fail-on compliance gate, and env/port
backend discovery (so it works with whatever fleet you run, under any name)."""

from __future__ import annotations

import os

from maritimeint import addins
from maritimeint.cli import main
from maritimeint.core import load_messages

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "demos", "ais_sample.csv")
AIS = os.path.join(ROOT, "demos", "ais_sample.json")


def test_csv_ingest():
    msgs = load_messages(CSV)
    assert len(msgs) == 4
    assert {m.mmsi for m in msgs} == {"210111000", "311333000"}
    assert msgs[0].name == "NEPTUNE STAR" and msgs[0].sog == 12.0


def test_csv_runs_through_analyze():
    msgs = load_messages(CSV)
    from maritimeint.core import analyze
    rep = analyze(msgs)
    assert rep["finding_counts"]["ais_gap"] >= 1   # NEPTUNE's 9h gap


def test_fail_on_gate_exit_code(capsys):
    # the demo has a HIGH-risk vessel (with sanctions) -> fail-on high must exit 2
    rc = main(["locate", AIS, "--sanctions", os.path.join(ROOT, "demos", "sanctions_sample.json"),
               "--fail-on", "high"])
    assert rc == 2
    # a clean run (no sanctions, tiny CSV with only a gap) below 'high' -> exit 0
    rc2 = main(["locate", CSV, "--fail-on", "high"])
    assert rc2 == 0


def test_discover_finds_backend_on_any_port():
    # a fleet "named something else" on a common port is still discovered
    def probe_stub(url):
        return ["my-fleet-model"] if url.endswith(":8000") else None
    found = addins.discover(probe_fn=probe_stub)
    assert any(base.endswith(":8000") for base, _ in found.values())
    # and an add-in becomes enabled off it even though it's not a named backend
    avail = {a["addin"]: a for a in addins.available(probe_fn=probe_stub)}
    assert avail["reasoning"]["enabled"] and avail["reasoning"]["base_url"].endswith(":8000")
