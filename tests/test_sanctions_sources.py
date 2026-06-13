"""Multi-source sanctions importers — parse each source's real format, then merge."""

from __future__ import annotations

import json
import os

from maritimeint import sanctions_sources as ss
from maritimeint.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMOS = os.path.join(ROOT, "demos")


def _read(name):
    with open(os.path.join(DEMOS, name), encoding="utf-8") as fh:
        return fh.read()


def test_ofsi_keeps_ships_and_extracts_imo():
    entries = ss.parse("ofsi", _read("ofsi_conlist_sample.csv"))
    names = {e["name"] for e in entries}
    assert names == {"NEPTUNE STAR", "GREY MARLIN"}        # the entity row is dropped
    neptune = next(e for e in entries if e["name"] == "NEPTUNE STAR")
    assert neptune["imo"] == "9700001" and neptune["source"] == "UK OFSI"
    assert neptune["flag"] == "Panama"


def test_eu_xml_vessels_only():
    entries = ss.parse("eu", _read("eu_consolidated_sample.xml"))
    assert {e["name"] for e in entries} == {"QUIET DAWN", "GREY MARLIN"}  # person dropped
    quiet = next(e for e in entries if e["name"] == "QUIET DAWN")
    assert quiet["imo"] == "9811000" and quiet["source"] == "EU consolidated"


def test_opensanctions_jsonl_vessels_only():
    entries = ss.parse("opensanctions", _read("opensanctions_sample.ftm.json"))
    assert {e["name"] for e in entries} == {"NEPTUNE STAR", "GREY MARLIN"}  # org dropped
    neptune = next(e for e in entries if e["name"] == "NEPTUNE STAR")
    assert neptune["imo"] == "9700001" and neptune["mmsi"] == "210111000"


def test_merge_dedupes_by_imo_and_unions_sources():
    ofsi = ss.parse("ofsi", _read("ofsi_conlist_sample.csv"))
    eu = ss.parse("eu", _read("eu_consolidated_sample.xml"))
    osa = ss.parse("opensanctions", _read("opensanctions_sample.ftm.json"))
    merged = ss.merge(ofsi, eu, osa)
    by_imo = {e["imo"]: e for e in merged if e["imo"]}
    # NEPTUNE STAR (OFSI + OpenSanctions), GREY MARLIN (all three), QUIET DAWN (EU)
    assert set(by_imo) == {"9700001", "9555123", "9811000"}
    # GREY MARLIN appears on three lists -> sources unioned
    marlin = by_imo["9555123"]
    assert "UK OFSI" in marlin["source"] and "EU consolidated" in marlin["source"]
    assert "OpenSanctions" in marlin["source"]
    # the MMSI from OpenSanctions fills in where OFSI had none
    assert by_imo["9700001"]["mmsi"] == "210111000"


def test_cli_import_sanctions_from_file(tmp_path):
    out = str(tmp_path / "s.json")
    rc = main(["import-sanctions", "--source", "ofsi", "--from-file",
               os.path.join(DEMOS, "ofsi_conlist_sample.csv"), "--out", out])
    assert rc == 0
    data = json.load(open(out, encoding="utf-8"))
    assert any(e["imo"] == "9700001" for e in data)


def test_unknown_source_raises():
    try:
        ss.parse("bogus", "x")
        assert False, "expected ValueError"
    except ValueError:
        pass
