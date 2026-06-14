"""maritimeint --emit: watchlist -> cognis-connect Findings -> platforms."""

from __future__ import annotations

import json
import os

import pytest

from maritimeint import connect
from maritimeint.cli import main

pytest.importorskip("cognis_connect")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIS = os.path.join(ROOT, "demos", "ais_sample.json")
SDN = os.path.join(ROOT, "demos", "ofac_sdn_sample.csv")


def _result():
    from maritimeint.core import load_messages
    from maritimeint.locate import locate
    from maritimeint.ofac import to_sanctions
    msgs = load_messages(AIS)
    static = {m.mmsi: {"name": m.name} for m in msgs}
    with open(SDN, encoding="utf-8") as fh:
        sanc = to_sanctions(fh.read())
    return locate(msgs, sanctions=sanc, static=static)


def test_watchlist_maps_to_findings():
    findings = connect.watchlist_to_findings(_result())
    sanctioned = [f for f in findings if f.severity == "critical"]
    assert sanctioned and all(f.source == "maritimeint" for f in findings)
    assert any(f.indicators.get("mmsi") == "210111000" for f in findings)


def test_forward_stix_bundle():
    bundle = connect.forward(_result(), "stix")
    assert bundle["type"] == "bundle" and bundle["objects"]


def test_cli_emit_slack_dry_run(tmp_path, capsys):
    out = str(tmp_path / "s.json")
    main(["import-ofac", "--from-file", SDN, "--out", out])
    rc = main(["locate", AIS, "--sanctions", out, "--emit", "slack",
               "--emit-url", "https://hook.test/x", "--emit-dry-run"])
    assert rc == 0
    err = capsys.readouterr().err
    assert '"dry_run": true' in err and "maritimeint watchlist" in err
