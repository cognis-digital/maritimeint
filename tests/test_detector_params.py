"""Parameter-sweep and cross-detector integration tests over synthetic scenes."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import (  # noqa: E402
    parse_messages, detect_gaps, detect_speed_jumps, detect_loitering,
    detect_rendezvous, detect_dark_rendezvous, analyze,
)
from maritimeint.zones import parse_zones  # noqa: E402


def rec(mmsi, hour, lat, lon, **kw):
    r = {"mmsi": mmsi, "timestamp": f"2026-01-04T{hour:02d}:00:00Z", "lat": lat, "lon": lon}
    r.update(kw)
    return r


class TestGapThresholdSweep:
    @pytest.mark.parametrize("gap_h,expect", [(2.0, 1), (5.0, 1), (5.0, 1),
                                              (6.0, 0), (10.0, 0)])
    def test_threshold(self, gap_h, expect):
        m = parse_messages([rec("A", 0, 26, 52), rec("A", 5, 26, 52)])
        assert len(detect_gaps(m, gap_hours=gap_h)) == expect


class TestSpeedThresholdSweep:
    @pytest.mark.parametrize("maxkn,expect", [(10.0, 1), (30.0, 1), (55.0, 0), (100.0, 0)])
    def test_threshold(self, maxkn, expect):
        # ~48 nm in 1h -> 48 kn
        m = parse_messages([rec("A", 0, 0, 0), rec("A", 1, 0.8, 0)])
        assert len(detect_speed_jumps(m, max_speed_kn=maxkn)) == expect


class TestLoiterSweep:
    @pytest.mark.parametrize("min_h,expect", [(2.0, 1), (5.0, 1), (6.0, 0), (12.0, 0)])
    def test_min_hours(self, min_h, expect):
        m = parse_messages([rec("A", h, 25.0, 55.0) for h in range(6)])
        assert len(detect_loitering(m, radius_nm=2.0, min_hours=min_h)) == expect

    @pytest.mark.parametrize("radius,expect", [(0.01, 0), (5.0, 1)])
    def test_radius(self, radius, expect):
        # points spread ~2 nm apart
        m = parse_messages([rec("A", h, 25.0 + h * 0.02, 55.0) for h in range(6)])
        assert len(detect_loitering(m, radius_nm=radius, min_hours=3.0)) == expect


class TestRendezvousSweep:
    def _pair(self, sep_deg):
        recs = []
        for h in range(4):
            recs.append(rec("A", h, 25.0, 55.0))
            recs.append(rec("B", h, 25.0 + sep_deg, 55.0))
        return parse_messages(recs)

    @pytest.mark.parametrize("prox,expect", [(0.1, 1), (0.5, 1), (5.0, 1)])
    def test_close_pair(self, prox, expect):
        assert len(detect_rendezvous(self._pair(0.001), proximity_nm=prox)) == expect

    def test_far_pair_never(self):
        assert detect_rendezvous(self._pair(1.0), proximity_nm=5.0) == []

    @pytest.mark.parametrize("min_min,expect", [(30.0, 1), (120.0, 1), (600.0, 0)])
    def test_min_minutes(self, min_min, expect):
        assert len(detect_rendezvous(self._pair(0.001), min_minutes=min_min)) == expect


class TestDarkRendezvousSweep:
    def _scene(self, b_lat):
        return parse_messages([
            rec("A", 0, 26.0, 52.0, name="D"), rec("A", 8, 26.1, 52.1, name="D"),
            {"mmsi": "B", "timestamp": "2026-01-04T03:00:00Z", "lat": b_lat, "lon": 52.0, "name": "L"},
        ])

    @pytest.mark.parametrize("prox,expect", [(1.0, 1), (5.0, 1)])
    def test_near(self, prox, expect):
        assert len(detect_dark_rendezvous(self._scene(26.0), proximity_nm=prox)) == expect

    def test_far_excluded(self):
        assert detect_dark_rendezvous(self._scene(40.0), proximity_nm=5.0) == []


class TestFullScenarioIntegration:
    """A synthetic multi-behaviour scene exercising several detectors + zones together."""

    def _scene(self):
        recs = []
        # vessel 1: goes dark 8h in a zone
        recs += [rec("V1", 0, 26.0, 52.0, name="DARK TANKER"),
                 rec("V1", 9, 26.6, 52.6, name="DARK TANKER")]
        # vessel 2: loiters
        recs += [rec("V2", h, 25.0, 55.0, name="LOITERER") for h in range(6)]
        # vessel 3: identity conflict + teleport
        recs += [rec("V3", 0, 20.0, 40.0, name="ALPHA"),
                 rec("V3", 1, 25.0, 40.0, name="BETA")]
        return parse_messages(recs)

    def test_multiple_detectors_fire(self):
        counts = analyze(self._scene())["finding_counts"]
        assert counts["ais_gap"] >= 1
        assert counts["loitering"] >= 1
        assert counts["speed_jump"] >= 1
        assert counts["spoofing"] >= 1

    def test_risk_ranking_nonempty(self):
        r = analyze(self._scene())
        assert len(r["risk_ranking"]) >= 3

    def test_zone_enrichment(self):
        zones = parse_zones([{"name": "Gulf EEZ", "kind": "eez",
                              "polygon": [[50, 25], [56, 25], [56, 30], [50, 30]]}])
        r = analyze(self._scene(), zones=zones)
        assert any("zones" in f for f in r["findings"])

    def test_top_vessel_is_flagged(self):
        r = analyze(self._scene())
        assert r["risk_ranking"][0]["risk_score"] > 0

    def test_serializable(self):
        import json
        json.dumps(analyze(self._scene()))
