"""Edge / air-gap data-feed ingestion tests. NO NETWORK.

Every test points ``COGNIS_FEEDS_CACHE`` at the committed offline fixture cache
(tests/fixtures/feeds_cache) and uses ``offline=True``, so CI stays green with
zero network access — the air-gap deployment story, exercised.
"""

from __future__ import annotations

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_CACHE = os.path.join(ROOT, "tests", "fixtures", "feeds_cache")


@pytest.fixture(autouse=True)
def _offline_cache(monkeypatch):
    """Force the feed cache at the committed fixture; guarantees no network."""
    monkeypatch.setenv("COGNIS_FEEDS_CACHE", FIXTURE_CACHE)


def test_catalog_is_filtered_to_maritime_feeds():
    from maritimeint import feeds
    ids = [f["id"] for f in feeds.relevant_catalog()["feeds"]]
    assert ids == ["ofac-sdn"]
    # the wider catalog is loadable but the tool only exposes its relevant slice
    assert "ofac-sdn" in feeds.RELEVANT_FEEDS


def test_list_feeds_reports_cached_fixture():
    from maritimeint import feeds
    rows = feeds.list_feeds()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "ofac-sdn"
    assert row["cached"] is True
    assert "treasury.gov/ofac" in row["url"]


def test_get_offline_serves_cached_csv():
    from maritimeint import feeds
    text = feeds.get("ofac-sdn", offline=True)
    assert isinstance(text, str)
    assert "NEPTUNE STAR" in text and "vessel" in text


def test_get_rejects_irrelevant_feed():
    from maritimeint import feeds
    with pytest.raises(KeyError):
        feeds.get("nvd-cve", offline=True)


def test_sanctioned_vessels_enrichment_from_edge_cache():
    """The real enrichment: OFAC designated vessels resolved through the edge
    cache parse straight into maritimeint sanctions entries."""
    from maritimeint import feeds
    entries = feeds.sanctioned_vessels(offline=True)
    assert [e["name"] for e in entries] == ["NEPTUNE STAR", "QUIET DAWN"]
    neptune = entries[0]
    assert neptune["imo"] == "9700001" and neptune["mmsi"] == "210111000"
    assert neptune["source"] == "OFAC SDN"


def test_offline_screening_flags_sanctioned_vessel():
    """End-to-end air-gap path: edge-cached OFAC -> locate flags the vessel."""
    from maritimeint import feeds
    from maritimeint.core import load_messages
    from maritimeint.locate import locate
    sanctions = feeds.sanctioned_vessels(offline=True)
    ais = os.path.join(ROOT, "demos", "ais_sample.json")
    msgs = load_messages(ais)
    static = {m.mmsi: {"name": m.name} for m in msgs}
    res = locate(msgs, sanctions=sanctions, static=static)
    top = res["watchlist"][0]
    assert top["mmsi"] == "210111000" and top["sanctioned"] is True


def test_cli_feeds_list_offline(capsys):
    from maritimeint.cli import main
    rc = main(["feeds", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ofac-sdn" in out


def test_cli_feeds_get_offline(capsys):
    from maritimeint.cli import main
    rc = main(["feeds", "get", "ofac-sdn", "--offline"])
    assert rc == 0
    assert "NEPTUNE STAR" in capsys.readouterr().out


def test_cli_import_ofac_from_feed_offline(tmp_path, capsys):
    from maritimeint.cli import main
    out = str(tmp_path / "ofac.json")
    rc = main(["import-ofac", "--from-feed", "--offline", "--out", out])
    assert rc == 0
    data = json.load(open(out, encoding="utf-8"))
    assert len(data) == 2 and data[0]["imo"] == "9700001"


def test_snapshot_roundtrip_offline(tmp_path, monkeypatch):
    """Export the fixture cache, import it into a fresh empty cache, re-serve."""
    from maritimeint import feeds, datafeeds
    snap = str(tmp_path / "feeds.tar.gz")
    n = feeds.snapshot_export(snap)
    assert n >= 1
    # point at a brand-new empty cache and import the snapshot
    empty = tmp_path / "enclave_cache"
    monkeypatch.setenv("COGNIS_FEEDS_CACHE", str(empty))
    imported = feeds.snapshot_import(snap)
    assert imported >= 1
    text = datafeeds.get("ofac-sdn", offline=True)
    assert "NEPTUNE STAR" in text
