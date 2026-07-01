"""Import/shape tests for feeds catalog wiring + extra locate() integration cases.

Network-touching feed fetch is NOT exercised (offline/CI safe); we assert the
catalog filtering, freshness shape, and error paths only.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages  # noqa: E402
from maritimeint.locate import locate, _reason  # noqa: E402
from maritimeint import feeds as F  # noqa: E402


def rec(mmsi, hour, lat, lon, **kw):
    r = {"mmsi": mmsi, "timestamp": f"2026-01-04T{hour:02d}:00:00Z", "lat": lat, "lon": lon}
    r.update(kw)
    return r


class TestFeedsCatalog:
    def test_relevant_catalog_shape(self):
        cat = F.relevant_catalog()
        assert "feeds" in cat and isinstance(cat["feeds"], list)

    def test_relevant_only_ofac(self):
        ids = {f["id"] for f in F.relevant_catalog()["feeds"]}
        assert ids <= set(F.RELEVANT_FEEDS)

    def test_list_feeds_has_freshness(self):
        for row in F.list_feeds():
            assert "cached_age_hours" in row

    def test_get_offline_missing_raises(self):
        # a feed with no cache, offline: should raise a clear error, not hang
        with pytest.raises((KeyError, FileNotFoundError, ConnectionError, ValueError)):
            F.get("no-such-feed", offline=True)


class TestReasonTemplates:
    @pytest.mark.parametrize("ftype", [
        "ais_gap", "speed_jump", "loitering", "static_pin", "spoofing",
        "rendezvous", "dark_rendezvous", "circle_spoof", "gps_jamming",
        "zone_transit", "port_call",
    ])
    def test_reason_nonempty(self, ftype):
        r = _reason({"type": ftype})
        assert isinstance(r, str) and r

    def test_unknown_type_falls_back(self):
        assert _reason({"type": "mystery"}) == "mystery"

    def test_no_type(self):
        assert _reason({}) == "anomaly"

    def test_port_call_sanctioned_tag(self):
        r = _reason({"type": "port_call", "port": "Kharg", "risk": "sanctioned", "dwell_hours": 5})
        assert "SANCTIONED" in r


class TestLocateIntegration:
    def _scene(self):
        recs = [
            rec("A1", 0, 26.0, 52.0, name="DARK"),
            rec("A1", 12, 26.6, 52.6, name="DARK"),  # gap + teleport-ish
            rec("B1", 0, 25.0, 55.0, name="LOIT"),
            rec("B1", 1, 25.0, 55.0, name="LOIT"),
            rec("B1", 5, 25.0, 55.0, name="LOIT"),
        ]
        return parse_messages(recs)

    def test_watchlist_ordered_by_score(self):
        wl = locate(self._scene())["watchlist"]
        scores = [v["score"] for v in wl]
        # non-sanctioned: sorted by score desc within the group
        assert scores == sorted(scores, reverse=True)

    def test_reasons_present_for_flagged(self):
        wl = locate(self._scene())["watchlist"]
        flagged = [v for v in wl if v["score"] > 0]
        assert flagged and all(v["reasons"] for v in flagged)

    def test_report_embedded(self):
        out = locate(self._scene())
        assert out["report"]["tool"] == "maritimeint"

    def test_tiers_valid(self):
        wl = locate(self._scene())["watchlist"]
        assert all(v["tier"] in ("HIGH", "MEDIUM", "LOW") for v in wl)

    def test_static_name_used(self):
        static = {"A1": {"name": "OVERRIDE NAME"}}
        wl = locate(self._scene(), static=static)["watchlist"]
        a1 = next(v for v in wl if v["mmsi"] == "A1")
        assert a1["name"] == "OVERRIDE NAME"

    def test_zones_kw_threads(self):
        from maritimeint.zones import parse_zones
        zs = parse_zones([{"name": "Z", "kind": "eez",
                           "polygon": [[50, 24], [56, 24], [56, 30], [50, 30]]}])
        out = locate(self._scene(), zones=zs)
        assert "watchlist" in out
