"""Edge-case tests for maritimeint.sanctions (screening) + locate() watchlist."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages  # noqa: E402
from maritimeint import sanctions as S  # noqa: E402
from maritimeint.sanctions import screen, load_sanctions, _norm  # noqa: E402
from maritimeint.locate import locate  # noqa: E402


SDN = [
    {"name": "GREY GHOST", "imo": "9176187", "mmsi": "477000001", "program": "IRAN", "source": "OFAC SDN"},
    {"name": "SHADOW STAR", "imo": "", "mmsi": "273000002", "program": "RUSSIA", "source": "OFAC SDN"},
]


class TestNorm:
    def test_upper_strip(self):
        assert _norm("  abc ") == "ABC"

    def test_none(self):
        assert _norm(None) == ""

    def test_empty(self):
        assert _norm("") == ""


class TestScreen:
    def test_match_mmsi(self):
        hits = screen("477000001", sanctions=SDN)
        assert len(hits) == 1 and "mmsi" in hits[0]["matched_on"]

    def test_match_imo(self):
        hits = screen("999", imo="9176187", sanctions=SDN)
        assert hits and "imo" in hits[0]["matched_on"]

    def test_match_name_case_insensitive(self):
        hits = screen("999", name="grey ghost", sanctions=SDN)
        assert hits and "name" in hits[0]["matched_on"]

    def test_multiple_match_keys(self):
        hits = screen("477000001", name="GREY GHOST", imo="9176187", sanctions=SDN)
        assert set(hits[0]["matched_on"]) == {"mmsi", "imo", "name"}

    def test_no_match(self):
        assert screen("000000000", sanctions=SDN) == []

    def test_empty_mmsi_no_match_on_empty_entry(self):
        # empty query fields must not match empty entry fields
        assert screen("", name="", imo="", sanctions=[{"name": "", "imo": "", "mmsi": ""}]) == []

    def test_none_sanctions(self):
        assert screen("123") == []

    def test_empty_sanctions(self):
        assert screen("123", sanctions=[]) == []

    def test_whitespace_name_normalized(self):
        assert screen("x", name="  grey ghost  ", sanctions=SDN)


class TestLoadSanctions:
    def test_list(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps(SDN), encoding="utf-8")
        assert len(load_sanctions(str(p))) == 2

    def test_entries_wrapper(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"entries": SDN}), encoding="utf-8")
        assert len(load_sanctions(str(p))) == 2

    def test_vessels_wrapper(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"vessels": SDN}), encoding="utf-8")
        assert len(load_sanctions(str(p))) == 2

    def test_bad_json(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text("{bad", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_sanctions(str(p))

    def test_scalar_rejected(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps(42), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON array"):
            load_sanctions(str(p))

    def test_bare_dict_rejected(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON array"):
            load_sanctions(str(p))


class TestLocate:
    def _msgs(self):
        recs = [
            {"mmsi": "477000001", "timestamp": "2026-01-04T00:00:00Z", "lat": 26.0, "lon": 52.0, "name": "GREY GHOST"},
            {"mmsi": "477000001", "timestamp": "2026-01-04T12:00:00Z", "lat": 26.5, "lon": 52.5, "name": "GREY GHOST"},
            {"mmsi": "999999999", "timestamp": "2026-01-04T00:00:00Z", "lat": 10.0, "lon": 10.0, "name": "CLEAN"},
            {"mmsi": "999999999", "timestamp": "2026-01-04T01:00:00Z", "lat": 10.01, "lon": 10.01, "name": "CLEAN"},
        ]
        return parse_messages(recs)

    def test_watchlist_shape(self):
        out = locate(self._msgs())
        assert "watchlist" in out and "report" in out

    def test_sanctioned_vessel_tier_high(self):
        static = {"477000001": {"name": "GREY GHOST", "imo": "9176187"}}
        out = locate(self._msgs(), sanctions=SDN, static=static)
        v = next(x for x in out["watchlist"] if x["mmsi"] == "477000001")
        assert v["sanctioned"] and v["tier"] == "HIGH"

    def test_sanctions_reason_first(self):
        static = {"477000001": {"name": "GREY GHOST"}}
        out = locate(self._msgs(), sanctions=SDN, static=static)
        v = next(x for x in out["watchlist"] if x["mmsi"] == "477000001")
        assert v["reasons"][0].startswith("ON SANCTIONS LIST")

    def test_sorted_sanctioned_first(self):
        static = {"477000001": {"name": "GREY GHOST"}}
        out = locate(self._msgs(), sanctions=SDN, static=static)
        assert out["watchlist"][0]["sanctioned"] is True

    def test_no_sanctions_no_flag(self):
        out = locate(self._msgs())
        assert all(not v["sanctioned"] for v in out["watchlist"])

    def test_empty_messages(self):
        out = locate([])
        assert out["watchlist"] == []

    def test_serializable(self):
        json.dumps(locate(self._msgs(), sanctions=SDN))
