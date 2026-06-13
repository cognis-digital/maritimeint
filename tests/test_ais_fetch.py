"""AIS fetcher — normalize a provider export into analyze/locate input."""

from __future__ import annotations

import json
import os

from maritimeint import ais_fetch as af
from maritimeint.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "demos", "ais_provider_sample.csv")


def test_normalize_maps_aliases_and_unix_time():
    recs = af.from_file(SAMPLE)
    # the row missing lat/lon is dropped
    assert len(recs) == 2
    r = recs[0]
    assert r["mmsi"] == "210111000" and r["name"] == "NEPTUNE STAR"
    assert r["lat"] == 25.401 and r["lon"] == 56.012 and r["sog"] == 11.4
    assert r["timestamp"].startswith("2024-06-1") and r["timestamp"].endswith("Z")  # unix -> ISO UTC


def test_normalize_records_skips_incomplete():
    recs = af.normalize_records([{"mmsi": "1", "lat": "10"}])  # no lon
    assert recs == []


def test_cli_fetch_ais_from_file_feeds_analyze(tmp_path):
    out = str(tmp_path / "ais.json")
    rc = main(["fetch-ais", "--source", "file", "--from-file", SAMPLE, "--out", out])
    assert rc == 0
    data = json.load(open(out, encoding="utf-8"))
    assert len(data) == 2
    # output is directly loadable by maritimeint
    from maritimeint.core import load_messages
    msgs = load_messages(out)
    assert {m.mmsi for m in msgs} == {"210111000", "636091234"}


def test_cli_fetch_ais_aishub_needs_username():
    rc = main(["fetch-ais", "--source", "aishub", "--out", "x.json"])
    assert rc == 1
