"""OFAC SDN importer — parse the real SDN.csv shape into maritimeint sanctions entries."""

from __future__ import annotations

import json
import os

from maritimeint import ofac
from maritimeint.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "demos", "ofac_sdn_sample.csv")


def test_parses_vessels_only_and_extracts_ids():
    with open(SAMPLE, encoding="utf-8") as fh:
        entries = ofac.to_sanctions(fh.read())
    # only the two 'vessel' rows; the entity + individual are skipped
    assert [e["name"] for e in entries] == ["NEPTUNE STAR", "QUIET DAWN"]
    neptune = entries[0]
    assert neptune["imo"] == "9700001" and neptune["mmsi"] == "210111000"
    assert neptune["program"] == "RUSSIA-EO14024" and neptune["source"] == "OFAC SDN"
    assert neptune["flag"] == "Panama"
    # second vessel: IMO but no MMSI in remarks
    assert entries[1]["imo"] == "9811000" and entries[1]["mmsi"] == ""


def test_empty_cells_become_blank():
    rows = ofac.parse_sdn_csv('"1","SHIP X","vessel","PROG","-0-","-0-","-0-","-0-","-0-","-0-","-0-","-0-"')
    assert rows[0]["call_sign"] == "" and rows[0]["imo"] == ""


def test_cli_import_ofac_from_file(tmp_path):
    out = str(tmp_path / "ofac.json")
    rc = main(["import-ofac", "--from-file", SAMPLE, "--out", out])
    assert rc == 0
    data = json.load(open(out, encoding="utf-8"))
    assert len(data) == 2 and data[0]["imo"] == "9700001"


def test_imported_list_feeds_locate(tmp_path):
    # the importer's output is directly usable by `locate --sanctions`
    out = str(tmp_path / "ofac.json")
    main(["import-ofac", "--from-file", SAMPLE, "--out", out])
    from maritimeint.core import load_messages
    from maritimeint.locate import locate
    from maritimeint.sanctions import load_sanctions
    ais = os.path.join(ROOT, "demos", "ais_sample.json")
    msgs = load_messages(ais)
    static = {m.mmsi: {"name": m.name} for m in msgs}
    res = locate(msgs, sanctions=load_sanctions(out), static=static)
    # NEPTUNE STAR (mmsi 210111000) is on the imported OFAC list -> flagged sanctioned
    top = res["watchlist"][0]
    assert top["mmsi"] == "210111000" and top["sanctioned"] is True
