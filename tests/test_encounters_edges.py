"""Edge-case tests for maritimeint.encounters (CPA/TCPA, shadowing, convoy, drift)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages  # noqa: E402
from maritimeint import encounters as E  # noqa: E402
from maritimeint.encounters import (  # noqa: E402
    detect_close_quarters,
    detect_shadowing,
    detect_convoy,
    detect_drift,
    analyze_encounters,
    _angle_diff,
    _local_xy,
    _interp,
    _track_speed_course,
    _pair_cpa,
)


def rec(mmsi, minute, lat, lon, **kw):
    r = {"mmsi": mmsi, "timestamp": f"2026-01-04T00:{minute:02d}:00Z",
         "lat": lat, "lon": lon}
    r.update(kw)
    return r


# --------------------------------------------------------------------------- #
# geo helpers
# --------------------------------------------------------------------------- #
class TestAngleDiff:
    def test_same(self):
        assert _angle_diff(90, 90) == 0

    def test_reciprocal(self):
        assert _angle_diff(0, 180) == 180

    def test_wrap(self):
        assert _angle_diff(350, 10) == pytest.approx(20)

    def test_small(self):
        assert _angle_diff(10, 350) == pytest.approx(20)

    def test_bounded_0_180(self):
        for a in range(0, 360, 37):
            for b in range(0, 360, 53):
                assert 0 <= _angle_diff(a, b) <= 180


class TestLocalXY:
    def test_origin_is_zero(self):
        assert _local_xy(10, 20, 10, 20) == (0.0, 0.0)

    def test_north_positive_y(self):
        _, y = _local_xy(11, 20, 10, 20)
        assert y == pytest.approx(60.0, abs=0.5)

    def test_east_positive_x(self):
        x, _ = _local_xy(10, 21, 10, 20)
        assert x > 0


class TestInterp:
    def _track(self):
        return parse_messages([rec("A", 0, 0, 0), rec("A", 10, 1, 0)])

    def test_midpoint(self):
        t = self._track()
        mid = t[0].timestamp + (t[1].timestamp - t[0].timestamp) / 2
        pos = _interp(t, mid)
        assert pos[0] == pytest.approx(0.5)

    def test_out_of_range_before(self):
        t = self._track()
        assert _interp(t, t[0].timestamp.replace(year=2020)) is None

    def test_out_of_range_after(self):
        t = self._track()
        assert _interp(t, t[-1].timestamp.replace(year=2030)) is None

    def test_empty_track(self):
        assert _interp([], self._track()[0].timestamp) is None


class TestTrackSpeedCourse:
    def test_reported_values_preferred(self):
        t = parse_messages([rec("A", 0, 0, 0, sog=12, cog=90), rec("A", 10, 0, 1, sog=12, cog=90)])
        sog, cog = _track_speed_course(t, 0)
        assert sog == 12 and cog == 90

    def test_derived_when_missing(self):
        t = parse_messages([rec("A", 0, 0, 0), rec("A", 30, 0, 1)])
        sog, cog = _track_speed_course(t, 1)
        assert sog > 0 and cog == pytest.approx(90, abs=2)

    def test_single_point_track(self):
        t = parse_messages([rec("A", 0, 0, 0)])
        assert _track_speed_course(t, 0) == (0.0, 0.0)


# --------------------------------------------------------------------------- #
# CPA / TCPA
# --------------------------------------------------------------------------- #
class TestPairCPA:
    def test_stationary_pair_range_is_cpa(self):
        a = parse_messages([rec("A", 0, 0, 0)])[0]
        b = parse_messages([rec("B", 0, 0, 0.1)])[0]
        cpa, tcpa, rng = _pair_cpa(a, (0, 0), b, (0, 0))
        assert cpa == pytest.approx(rng)

    def test_converging_gives_small_cpa(self):
        a = parse_messages([rec("A", 0, 0, 0)])[0]
        b = parse_messages([rec("B", 0, 0, 0.2)])[0]  # ~12 nm east
        # a heading east, b heading west -> converge
        cpa, tcpa, rng = _pair_cpa(a, (10, 90), b, (10, 270))
        assert cpa < rng and tcpa >= 0


class TestCloseQuarters:
    def test_converging_flagged(self):
        recs = []
        for mi in range(5):
            recs.append(rec("A", mi, 0.0, mi * 0.02, sog=60, cog=90))
            recs.append(rec("B", mi, 0.0, 0.5 - mi * 0.02, sog=60, cog=270))
        f = detect_close_quarters(parse_messages(recs), cpa_nm=0.5, tcpa_max_minutes=30)
        assert any(x["type"] == "close_quarters" for x in f)

    def test_parallel_far_not_flagged(self):
        recs = []
        for mi in range(5):
            recs.append(rec("A", mi, 0.0, mi * 0.02, sog=60, cog=90))
            recs.append(rec("B", mi, 1.0, mi * 0.02, sog=60, cog=90))
        assert detect_close_quarters(parse_messages(recs)) == []

    def test_single_vessel_no_pairs(self):
        m = parse_messages([rec("A", mi, 0, mi * 0.01) for mi in range(5)])
        assert detect_close_quarters(m) == []

    def test_empty(self):
        assert detect_close_quarters([]) == []


# --------------------------------------------------------------------------- #
# shadowing
# --------------------------------------------------------------------------- #
class TestShadowing:
    def _trail(self, minutes=180, step=15):
        recs = []
        for t in range(0, minutes + 1, step):
            lat_a = t / 600.0
            recs.append({"mmsi": "LEAD", "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                         "lat": lat_a, "lon": 50.0, "name": "LEAD", "sog": 6, "cog": 0})
            recs.append({"mmsi": "TAIL", "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                         "lat": lat_a - 0.05, "lon": 50.0, "name": "TAIL", "sog": 6, "cog": 0})
        return parse_messages(recs)

    def test_shadow_detected(self):
        f = detect_shadowing(self._trail(), standoff_max_nm=8.0, min_minutes=90.0)
        assert len(f) == 1
        assert set(f[0]["vessels"]) == {"LEAD", "TAIL"}

    def test_leader_follower_labelled(self):
        f = detect_shadowing(self._trail())[0]
        assert f["leader"] in ("LEAD", "TAIL") and f["follower"] != f["leader"]

    def test_too_short_not_flagged(self):
        assert detect_shadowing(self._trail(minutes=30)) == []

    def test_diverging_course_not_flagged(self):
        recs = []
        for t in range(0, 200, 15):
            recs.append({"mmsi": "A", "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                         "lat": t / 600.0, "lon": 50.0, "sog": 6, "cog": 0})
            recs.append({"mmsi": "B", "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                         "lat": 0.0, "lon": 50.0 + t / 600.0, "sog": 6, "cog": 90})
        assert detect_shadowing(parse_messages(recs)) == []

    def test_empty(self):
        assert detect_shadowing([]) == []


# --------------------------------------------------------------------------- #
# convoy
# --------------------------------------------------------------------------- #
class TestConvoy:
    def _convoy(self):
        recs = []
        for e in range(4):  # epochs at 0/40/80/120 min
            t = e * 40
            for k, mmsi in enumerate(("C1", "C2", "C3")):
                recs.append({"mmsi": mmsi,
                             "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                             "lat": 25.0 + e * 0.1 + k * 0.005, "lon": 55.0,
                             "name": mmsi, "sog": 10, "cog": 0})
        return parse_messages(recs)

    def test_convoy_detected(self):
        f = detect_convoy(self._convoy(), cluster_nm=3.0, min_vessels=3)
        assert len(f) == 1 and f[0]["vessel_count"] == 3

    def test_below_min_vessels(self):
        f = detect_convoy(self._convoy(), min_vessels=5)
        assert f == []

    def test_scattered_not_convoy(self):
        recs = []
        for e in range(4):
            t = e * 40
            for k, mmsi in enumerate(("C1", "C2", "C3")):
                recs.append({"mmsi": mmsi,
                             "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                             "lat": 25.0 + k * 5.0, "lon": 55.0 + k * 5.0,
                             "sog": 10, "cog": 0})
        assert detect_convoy(parse_messages(recs)) == []

    def test_too_few_tracks(self):
        m = parse_messages([rec("A", 0, 25, 55), rec("B", 0, 25, 55)])
        assert detect_convoy(m, min_vessels=3) == []

    def test_empty(self):
        assert detect_convoy([]) == []


# --------------------------------------------------------------------------- #
# drift
# --------------------------------------------------------------------------- #
class TestDrift:
    def _adrift(self):
        # near-zero SOG, heading swinging widely across the run
        pts = [(0.000, 0.000), (0.0005, 0.0002), (0.0004, 0.0009), (0.0011, 0.0007),
               (0.0006, 0.0015)]
        recs = []
        for i, (dlat, dlon) in enumerate(pts):
            t = i * 30
            recs.append({"mmsi": "DR", "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                         "lat": 25.0 + dlat, "lon": 55.0 + dlon, "name": "ADRIFT", "sog": 0.3})
        return parse_messages(recs)

    def test_drift_detected(self):
        f = detect_drift(self._adrift(), max_sog_kn=1.5, min_minutes=60.0)
        assert len(f) == 1 and f[0]["mmsi"] == "DR"

    def test_powered_steady_not_drift(self):
        recs = [{"mmsi": "P", "timestamp": f"2026-01-04T{i:02d}:00:00Z",
                 "lat": 25.0 + i * 0.2, "lon": 55.0, "sog": 12} for i in range(5)]
        assert detect_drift(parse_messages(recs)) == []

    def test_too_short_not_flagged(self):
        recs = [{"mmsi": "D", "timestamp": f"2026-01-04T00:{i:02d}:00Z",
                 "lat": 25.0, "lon": 55.0, "sog": 0.2} for i in range(2)]
        assert detect_drift(parse_messages(recs)) == []

    def test_empty(self):
        assert detect_drift([]) == []


# --------------------------------------------------------------------------- #
# analyze_encounters
# --------------------------------------------------------------------------- #
class TestAnalyzeEncounters:
    def test_shape(self):
        r = analyze_encounters([])
        assert r["mode"] == "encounters"
        assert set(r["finding_counts"]) == {"close_quarters", "shadowing", "convoy", "drift"}

    def test_counts_consistent(self):
        recs = []
        for e in range(4):
            t = e * 40
            for k, mmsi in enumerate(("C1", "C2", "C3")):
                recs.append({"mmsi": mmsi,
                             "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                             "lat": 25.0 + e * 0.1 + k * 0.005, "lon": 55.0,
                             "name": mmsi, "sog": 10, "cog": 0})
        r = analyze_encounters(parse_messages(recs))
        assert r["finding_counts"]["convoy"] == len([f for f in r["findings"] if f["type"] == "convoy"])

    def test_serializable(self):
        import json
        json.dumps(analyze_encounters([]))
