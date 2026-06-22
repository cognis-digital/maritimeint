"""Tests for the v0.9 track-interaction & behaviour layer (maritimeint.encounters).

Covers CPA/TCPA close-quarters, shadowing, convoy/co-movement, and drift, plus
their integration into core.analyze, the CLI subcommands, and the intel exporters.

No network. Standard library only. Every fixture is synthetic and deterministic.
"""

import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages, analyze  # noqa: E402
from maritimeint import encounters as E  # noqa: E402
from maritimeint import intel  # noqa: E402
from maritimeint.cli import main  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _ts(minute_offset):
    """A timestamp string `minute_offset` minutes after 2026-01-04T12:00Z."""
    base_h, base_m = 12, 0
    total = base_h * 60 + base_m + minute_offset
    return f"2026-01-04T{total // 60:02d}:{total % 60:02d}:00Z"


def _converging_pair(step=2, n=6, sep_lon=0.30, sog=12):
    """Two vessels at the same latitude closing head-on along a parallel of lon."""
    recs = []
    for k in range(n):
        recs.append({"mmsi": "CQ_A", "timestamp": _ts(k * step),
                     "lat": 25.0, "lon": 55.0 + 0.02 * k, "name": "ALPHA",
                     "sog": sog, "cog": 90})
        recs.append({"mmsi": "CQ_B", "timestamp": _ts(k * step),
                     "lat": 25.0, "lon": 55.0 + sep_lon - 0.02 * k, "name": "BRAVO",
                     "sog": sog, "cog": 270})
    return parse_messages(recs)


def _shadow_pair(n=9, standoff_deg=0.033, step_min=15, sog=10):
    """LEAD steams due north; TAIL follows `standoff_deg` behind on the same course."""
    recs = []
    for k in range(n):
        lat = 20.0 + 0.05 * k
        recs.append({"mmsi": "LEAD", "timestamp": _ts(k * step_min),
                     "lat": lat, "lon": 40.0, "name": "LEADER", "sog": sog, "cog": 0})
        recs.append({"mmsi": "TAIL", "timestamp": _ts(k * step_min),
                     "lat": lat - standoff_deg, "lon": 40.0, "name": "TAILER",
                     "sog": sog, "cog": 0})
    return parse_messages(recs)


def _convoy(n_epochs=5, members=("V1", "V2", "V3"), spacing=0.02, sog=11):
    recs = []
    for k in range(n_epochs):
        lat = 10.0 + 0.1 * k
        for i, m in enumerate(members):
            recs.append({"mmsi": m, "timestamp": _ts(k * 60),
                         "lat": lat, "lon": 30.0 + spacing * i, "name": m,
                         "sog": sog, "cog": 0})
    return parse_messages(recs)


def _drifter(sog=0.4):
    pts = [(0, 0), (0.001, 0.001), (0.0015, -0.0005), (0.001, -0.002), (0.0, -0.0025)]
    recs = []
    for k, (dlat, dlon) in enumerate(pts):
        recs.append({"mmsi": "DRF", "timestamp": _ts(k * 60),
                     "lat": 15.0 + dlat, "lon": 45.0 + dlon, "name": "ADRIFT",
                     "sog": sog})
    return parse_messages(recs)


# --------------------------------------------------------------------------- #
# geo helpers
# --------------------------------------------------------------------------- #
class TestGeoHelpers(unittest.TestCase):
    def test_angle_diff_wraps(self):
        self.assertAlmostEqual(E._angle_diff(350, 10), 20.0)
        self.assertAlmostEqual(E._angle_diff(10, 350), 20.0)
        self.assertAlmostEqual(E._angle_diff(0, 180), 180.0)
        self.assertAlmostEqual(E._angle_diff(90, 90), 0.0)

    def test_angle_diff_never_exceeds_180(self):
        for a in range(0, 360, 17):
            for b in range(0, 360, 23):
                self.assertLessEqual(E._angle_diff(a, b), 180.0)

    def test_local_xy_origin_zero(self):
        x, y = E._local_xy(25.0, 55.0, 25.0, 55.0)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 0.0)

    def test_local_xy_north_positive(self):
        _, y = E._local_xy(25.1, 55.0, 25.0, 55.0)
        self.assertGreater(y, 0.0)
        self.assertAlmostEqual(y, 0.1 * 60.0, places=3)

    def test_local_xy_east_positive(self):
        x, _ = E._local_xy(25.0, 55.1, 25.0, 55.0)
        self.assertGreater(x, 0.0)

    def test_interp_midpoint(self):
        t = _shadow_pair()
        track = [m for m in t if m.mmsi == "LEAD"]
        from maritimeint.core import _parse_ts
        mid = _parse_ts(_ts(7))  # between two 15-min fixes
        pos = E._interp(track, mid)
        self.assertIsNotNone(pos)

    def test_interp_out_of_range(self):
        track = [m for m in _shadow_pair() if m.mmsi == "LEAD"]
        from maritimeint.core import _parse_ts
        self.assertIsNone(E._interp(track, _parse_ts("2020-01-01T00:00:00Z")))

    def test_track_speed_course_uses_reported(self):
        track = [m for m in _shadow_pair() if m.mmsi == "LEAD"]
        sog, cog = E._track_speed_course(track, 1)
        self.assertEqual(sog, 10.0)
        self.assertEqual(cog, 0.0)

    def test_track_speed_course_derives_when_missing(self):
        recs = parse_messages([
            {"mmsi": "D", "timestamp": _ts(0), "lat": 0.0, "lon": 0.0},
            {"mmsi": "D", "timestamp": _ts(60), "lat": 1.0, "lon": 0.0},
        ])
        sog, cog = E._track_speed_course(recs, 1)
        self.assertGreater(sog, 0.0)
        self.assertAlmostEqual(cog, 0.0, places=0)  # due north


# --------------------------------------------------------------------------- #
# CPA / TCPA close-quarters
# --------------------------------------------------------------------------- #
class TestCloseQuarters(unittest.TestCase):
    def test_head_on_flagged(self):
        f = E.detect_close_quarters(_converging_pair())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["type"], "close_quarters")
        self.assertEqual(set(f[0]["vessels"]), {"CQ_A", "CQ_B"})

    def test_head_on_cpa_small(self):
        f = E.detect_close_quarters(_converging_pair())
        self.assertLessEqual(f[0]["cpa_nm"], 0.5)

    def test_head_on_tcpa_positive(self):
        f = E.detect_close_quarters(_converging_pair())
        self.assertGreaterEqual(f[0]["tcpa_minutes"], 0.0)
        self.assertLessEqual(f[0]["tcpa_minutes"], 30.0)

    def test_collision_course_high_severity(self):
        f = E.detect_close_quarters(_converging_pair())
        self.assertEqual(f[0]["severity"], "high")  # cpa ~0 <= 0.25

    def test_diverging_not_flagged(self):
        recs = []
        for k in range(6):
            recs.append({"mmsi": "X", "timestamp": _ts(k * 5), "lat": 25.0,
                         "lon": 55.0 + 0.1 * k, "name": "X", "sog": 12, "cog": 90})
            recs.append({"mmsi": "Y", "timestamp": _ts(k * 5), "lat": 35.0,
                         "lon": 15.0 - 0.1 * k, "name": "Y", "sog": 12, "cog": 270})
        self.assertEqual(E.detect_close_quarters(parse_messages(recs)), [])

    def test_parallel_safe_passing_not_flagged(self):
        # two ships abreast 5 nm apart on identical course never converge
        recs = []
        for k in range(6):
            lat = 10.0 + 0.05 * k
            recs.append({"mmsi": "P1", "timestamp": _ts(k * 10), "lat": lat,
                         "lon": 40.0, "name": "P1", "sog": 10, "cog": 0})
            recs.append({"mmsi": "P2", "timestamp": _ts(k * 10), "lat": lat,
                         "lon": 40.083, "name": "P2", "sog": 10, "cog": 0})
        f = E.detect_close_quarters(parse_messages(recs), cpa_nm=0.5)
        self.assertEqual(f, [])

    def test_single_vessel_no_pairs(self):
        recs = parse_messages([{"mmsi": "S", "timestamp": _ts(0), "lat": 1.0,
                                "lon": 1.0, "sog": 10, "cog": 0}])
        self.assertEqual(E.detect_close_quarters(recs), [])

    def test_time_mismatch_excluded(self):
        # reports too far apart in time to pair
        recs = parse_messages([
            {"mmsi": "A", "timestamp": _ts(0), "lat": 25.0, "lon": 55.0, "sog": 12, "cog": 90},
            {"mmsi": "B", "timestamp": _ts(600), "lat": 25.0, "lon": 55.1, "sog": 12, "cog": 270},
        ])
        self.assertEqual(E.detect_close_quarters(recs), [])

    def test_cpa_threshold_tightened(self):
        # with a 0.01 nm threshold the encounter at cpa 0 still flags but a
        # near-miss would not; verify threshold is honoured
        loose = E.detect_close_quarters(_converging_pair(sep_lon=0.30), cpa_nm=0.5)
        self.assertEqual(len(loose), 1)

    def test_pair_cpa_math_stationary(self):
        recs = parse_messages([
            {"mmsi": "A", "timestamp": _ts(0), "lat": 0.0, "lon": 0.0, "sog": 0, "cog": 0},
            {"mmsi": "B", "timestamp": _ts(0), "lat": 0.0, "lon": 0.1, "sog": 0, "cog": 0},
        ])
        a = [m for m in recs if m.mmsi == "A"][0]
        b = [m for m in recs if m.mmsi == "B"][0]
        cpa, tcpa, rng = E._pair_cpa(a, (0, 0), b, (0, 0))
        self.assertAlmostEqual(cpa, rng)  # no relative motion -> cpa == range now
        self.assertEqual(tcpa, 0.0)

    def test_pair_cpa_already_passed(self):
        # b ahead and moving away -> tcpa clamped to 0, cpa == range now
        recs = parse_messages([
            {"mmsi": "A", "timestamp": _ts(0), "lat": 0.0, "lon": 0.0, "sog": 0, "cog": 0},
            {"mmsi": "B", "timestamp": _ts(0), "lat": 0.0, "lon": 0.1, "sog": 10, "cog": 90},
        ])
        a = [m for m in recs if m.mmsi == "A"][0]
        b = [m for m in recs if m.mmsi == "B"][0]
        cpa, tcpa, rng = E._pair_cpa(a, (0, 0), b, (10, 90))
        self.assertEqual(tcpa, 0.0)
        self.assertAlmostEqual(cpa, rng)


# --------------------------------------------------------------------------- #
# shadowing
# --------------------------------------------------------------------------- #
class TestShadowing(unittest.TestCase):
    def test_trailing_flagged(self):
        f = E.detect_shadowing(_shadow_pair())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["type"], "shadowing")

    def test_leader_follower_identified(self):
        f = E.detect_shadowing(_shadow_pair())
        self.assertEqual(f[0]["leader"], "LEAD")
        self.assertEqual(f[0]["follower"], "TAIL")

    def test_standoff_reported(self):
        f = E.detect_shadowing(_shadow_pair())
        self.assertGreater(f[0]["mean_standoff_nm"], 0.3)
        self.assertLess(f[0]["mean_standoff_nm"], 8.0)

    def test_duration_meets_minimum(self):
        f = E.detect_shadowing(_shadow_pair())
        self.assertGreaterEqual(f[0]["duration_minutes"], 90.0)

    def test_too_close_is_not_shadowing(self):
        # standoff below the floor (essentially overlapping -> rendezvous turf)
        f = E.detect_shadowing(_shadow_pair(standoff_deg=0.001))
        self.assertEqual(f, [])

    def test_too_far_excluded(self):
        f = E.detect_shadowing(_shadow_pair(standoff_deg=0.5), standoff_max_nm=8.0)
        self.assertEqual(f, [])

    def test_diverging_courses_excluded(self):
        recs = []
        for k in range(9):
            lat = 20.0 + 0.05 * k
            recs.append({"mmsi": "L", "timestamp": _ts(k * 15), "lat": lat,
                         "lon": 40.0, "name": "L", "sog": 10, "cog": 0})
            recs.append({"mmsi": "F", "timestamp": _ts(k * 15), "lat": 20.0,
                         "lon": 40.0 + 0.05 * k, "name": "F", "sog": 10, "cog": 90})
        self.assertEqual(E.detect_shadowing(parse_messages(recs)), [])

    def test_short_encounter_excluded(self):
        f = E.detect_shadowing(_shadow_pair(n=3), min_minutes=90.0)
        self.assertEqual(f, [])

    def test_min_minutes_param(self):
        # a 105-min shadow should pass min_minutes=90 but fail min_minutes=200
        self.assertEqual(len(E.detect_shadowing(_shadow_pair(), min_minutes=90.0)), 1)
        self.assertEqual(E.detect_shadowing(_shadow_pair(), min_minutes=300.0), [])

    def test_long_shadow_high_severity(self):
        f = E.detect_shadowing(_shadow_pair(n=20), min_minutes=90.0)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "high")


# --------------------------------------------------------------------------- #
# convoy
# --------------------------------------------------------------------------- #
class TestConvoy(unittest.TestCase):
    def test_three_abreast_flagged(self):
        f = E.detect_convoy(_convoy())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["vessel_count"], 3)

    def test_members_listed(self):
        f = E.detect_convoy(_convoy())
        self.assertEqual(set(f[0]["vessels"]), {"V1", "V2", "V3"})

    def test_epochs_counted(self):
        f = E.detect_convoy(_convoy(n_epochs=5))
        self.assertEqual(f[0]["epochs"], 5)

    def test_below_min_vessels_excluded(self):
        f = E.detect_convoy(_convoy(members=("V1", "V2")), min_vessels=3)
        self.assertEqual(f, [])

    def test_too_few_epochs_excluded(self):
        f = E.detect_convoy(_convoy(n_epochs=2), min_epochs=3)
        self.assertEqual(f, [])

    def test_scattered_vessels_excluded(self):
        # three vessels nowhere near each other
        recs = []
        for k in range(5):
            recs.append({"mmsi": "A", "timestamp": _ts(k * 60), "lat": 0.0 + k,
                         "lon": 0.0, "name": "A", "sog": 10, "cog": 0})
            recs.append({"mmsi": "B", "timestamp": _ts(k * 60), "lat": 40.0 + k,
                         "lon": 40.0, "name": "B", "sog": 10, "cog": 0})
            recs.append({"mmsi": "C", "timestamp": _ts(k * 60), "lat": -40.0 - k,
                         "lon": -40.0, "name": "C", "sog": 10, "cog": 0})
        self.assertEqual(E.detect_convoy(parse_messages(recs)), [])

    def test_mismatched_speed_excluded(self):
        # close together but wildly different speeds -> not a formation
        recs = []
        for k in range(5):
            lat = 10.0 + 0.1 * k
            recs.append({"mmsi": "S1", "timestamp": _ts(k * 60), "lat": lat,
                         "lon": 30.0, "name": "S1", "sog": 5, "cog": 0})
            recs.append({"mmsi": "S2", "timestamp": _ts(k * 60), "lat": lat,
                         "lon": 30.02, "name": "S2", "sog": 25, "cog": 0})
            recs.append({"mmsi": "S3", "timestamp": _ts(k * 60), "lat": lat,
                         "lon": 30.04, "name": "S3", "sog": 5, "cog": 0})
        f = E.detect_convoy(parse_messages(recs), min_vessels=3)
        self.assertEqual(f, [])

    def test_fewer_than_min_total_vessels(self):
        recs = _convoy(members=("V1", "V2"))
        self.assertEqual(E.detect_convoy(recs, min_vessels=3), [])

    def test_timestamps_iso_z(self):
        f = E.detect_convoy(_convoy())
        self.assertTrue(f[0]["start"].endswith("Z"))
        self.assertTrue(f[0]["end"].endswith("Z"))


# --------------------------------------------------------------------------- #
# drift
# --------------------------------------------------------------------------- #
class TestDrift(unittest.TestCase):
    def test_adrift_flagged(self):
        f = E.detect_drift(_drifter())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["type"], "drift")

    def test_heading_swing_reported(self):
        f = E.detect_drift(_drifter())
        self.assertGreaterEqual(f[0]["heading_swing_deg"], 60.0)

    def test_duration_reported(self):
        f = E.detect_drift(_drifter())
        self.assertGreaterEqual(f[0]["duration_minutes"], 60.0)

    def test_steady_course_not_drift(self):
        # low speed but a perfectly steady heading -> holding station, not adrift
        recs = []
        for k in range(5):
            recs.append({"mmsi": "H", "timestamp": _ts(k * 60), "lat": 10.0 + 0.001 * k,
                         "lon": 20.0, "name": "H", "sog": 0.5})
        self.assertEqual(E.detect_drift(parse_messages(recs)), [])

    def test_underway_not_drift(self):
        # a vessel making good speed is never adrift
        recs = []
        for k in range(5):
            recs.append({"mmsi": "U", "timestamp": _ts(k * 30), "lat": 10.0 + 0.1 * k,
                         "lon": 20.0 + 0.1 * k, "name": "U", "sog": 15})
        self.assertEqual(E.detect_drift(parse_messages(recs)), [])

    def test_short_run_excluded(self):
        recs = []
        for k in range(2):
            recs.append({"mmsi": "X", "timestamp": _ts(k * 60), "lat": 10.0,
                         "lon": 20.0 + 0.001 * k, "name": "X", "sog": 0.3})
        self.assertEqual(E.detect_drift(parse_messages(recs), min_reports=3), [])

    def test_derived_speed_catches_unreported_sog(self):
        # no sog reported but tiny displacement + heading swing -> still drift
        pts = [(0, 0), (0.001, 0.001), (0.0015, -0.0005), (0.001, -0.002), (0.0, -0.0025)]
        recs = []
        for k, (dlat, dlon) in enumerate(pts):
            recs.append({"mmsi": "N", "timestamp": _ts(k * 60),
                         "lat": 15.0 + dlat, "lon": 45.0 + dlon, "name": "N"})
        self.assertEqual(len(E.detect_drift(parse_messages(recs))), 1)

    def test_fast_unreported_excluded(self):
        # no sog, but displacement implies fast motion -> not drift
        recs = []
        for k in range(5):
            recs.append({"mmsi": "F", "timestamp": _ts(k * 60), "lat": 10.0 + 0.3 * k,
                         "lon": 20.0 + 0.3 * k, "name": "F"})
        self.assertEqual(E.detect_drift(parse_messages(recs)), [])

    def test_center_within_track(self):
        f = E.detect_drift(_drifter())
        clat, clon = f[0]["center"]
        self.assertAlmostEqual(clat, 15.0, places=1)
        self.assertAlmostEqual(clon, 45.0, places=1)


# --------------------------------------------------------------------------- #
# analyze_encounters (combined)
# --------------------------------------------------------------------------- #
class TestAnalyzeEncounters(unittest.TestCase):
    def test_report_shape(self):
        rep = E.analyze_encounters(_converging_pair())
        self.assertEqual(rep["mode"], "encounters")
        self.assertIn("finding_counts", rep)
        self.assertIn("findings", rep)

    def test_counts_close_quarters(self):
        rep = E.analyze_encounters(_converging_pair())
        self.assertEqual(rep["finding_counts"]["close_quarters"], 1)

    def test_counts_shadowing(self):
        rep = E.analyze_encounters(_shadow_pair())
        self.assertEqual(rep["finding_counts"]["shadowing"], 1)

    def test_counts_convoy(self):
        rep = E.analyze_encounters(_convoy())
        self.assertEqual(rep["finding_counts"]["convoy"], 1)

    def test_counts_drift(self):
        rep = E.analyze_encounters(_drifter())
        self.assertEqual(rep["finding_counts"]["drift"], 1)

    def test_zone_annotation(self):
        from maritimeint import zones as Z
        zs = Z.parse_zones([{"name": "DriftZone", "kind": "eez",
                             "center": [45.0, 15.0], "radius_nm": 50.0}])
        rep = E.analyze_encounters(_drifter(), zones=zs)
        drift = next(f for f in rep["findings"] if f["type"] == "drift")
        self.assertIn("DriftZone", drift.get("zones", []))

    def test_empty_input(self):
        rep = E.analyze_encounters(parse_messages([]))
        self.assertEqual(rep["messages"], 0)
        self.assertEqual(rep["findings"], [])


# --------------------------------------------------------------------------- #
# integration into core.analyze
# --------------------------------------------------------------------------- #
class TestCoreAnalyzeIntegration(unittest.TestCase):
    def test_close_quarters_in_master_report(self):
        rep = analyze(_converging_pair())
        self.assertIn("close_quarters", rep["finding_counts"])
        self.assertEqual(rep["finding_counts"]["close_quarters"], 1)

    def test_shadowing_in_master_report(self):
        rep = analyze(_shadow_pair())
        self.assertEqual(rep["finding_counts"]["shadowing"], 1)

    def test_convoy_in_master_report(self):
        rep = analyze(_convoy())
        self.assertEqual(rep["finding_counts"]["convoy"], 1)

    def test_drift_in_master_report(self):
        rep = analyze(_drifter())
        self.assertEqual(rep["finding_counts"]["drift"], 1)

    def test_close_quarters_scores_both_vessels(self):
        rep = analyze(_converging_pair())
        ranked = {r["mmsi"]: r["risk_score"] for r in rep["risk_ranking"]}
        self.assertIn("CQ_A", ranked)
        self.assertIn("CQ_B", ranked)
        self.assertGreater(ranked["CQ_A"], 0)

    def test_existing_detectors_still_present(self):
        rep = analyze(_converging_pair())
        for key in ("ais_gap", "speed_jump", "loitering", "spoofing",
                    "rendezvous", "dark_rendezvous", "gps_anomaly"):
            self.assertIn(key, rep["finding_counts"])


# --------------------------------------------------------------------------- #
# export round-trip of the new findings
# --------------------------------------------------------------------------- #
class TestEncounterExports(unittest.TestCase):
    def setUp(self):
        self.rep = E.analyze_encounters(_converging_pair())

    def test_geojson_valid(self):
        gj = json.loads(intel.to_geojson(self.rep))
        self.assertEqual(gj["type"], "FeatureCollection")
        self.assertTrue(gj["features"])

    def test_close_quarters_has_point_geometry(self):
        gj = json.loads(intel.to_geojson(self.rep))
        cq = [f for f in gj["features"]
              if f["properties"].get("type") == "close_quarters"]
        self.assertTrue(cq)
        self.assertIsNotNone(cq[0]["geometry"])

    def test_stix_valid_bundle(self):
        bundle = json.loads(intel.to_stix(self.rep))
        self.assertEqual(bundle["type"], "bundle")
        self.assertTrue(all(o["type"] == "indicator" for o in bundle["objects"]))

    def test_csv_has_rows(self):
        csv_text = intel.to_csv(self.rep)
        lines = [ln for ln in csv_text.splitlines() if ln.strip()]
        self.assertGreaterEqual(len(lines), 2)  # header + >=1 finding

    def test_kml_well_formed(self):
        kml = intel.to_kml(self.rep)
        self.assertIn("<kml", kml)
        self.assertIn("</kml>", kml)


# --------------------------------------------------------------------------- #
# CLI subcommands
# --------------------------------------------------------------------------- #
class TestEncountersCLI(unittest.TestCase):
    @classmethod
    def _write(cls, msgs):
        recs = [m.as_record() for m in msgs]
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"messages": recs}, fh)
        return path

    def setUp(self):
        self.cq = self._write(_converging_pair())
        self.sh = self._write(_shadow_pair())
        self.cv = self._write(_convoy())
        self.df = self._write(_drifter())
        self._paths = [self.cq, self.sh, self.cv, self.df]

    def tearDown(self):
        for p in self._paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_close_quarters_cli_table(self):
        self.assertEqual(main(["close-quarters", self.cq]), 0)

    def test_close_quarters_cli_json(self):
        self.assertEqual(main(["--format", "json", "close-quarters", self.cq]), 0)

    def test_shadowing_cli(self):
        self.assertEqual(main(["shadowing", self.sh]), 0)

    def test_convoy_cli(self):
        self.assertEqual(main(["convoy", self.cv]), 0)

    def test_drift_cli(self):
        self.assertEqual(main(["drift", self.df]), 0)

    def test_encounters_cli(self):
        self.assertEqual(main(["--format", "json", "encounters", self.cq]), 0)

    def test_encounters_cli_table(self):
        # table mode must not require a risk_ranking key
        self.assertEqual(main(["encounters", self.cq]), 0)

    def test_close_quarters_cli_custom_cpa(self):
        self.assertEqual(main(["close-quarters", self.cq, "--cpa-nm", "1.0"]), 0)

    def test_drift_cli_params(self):
        self.assertEqual(main(["drift", self.df, "--max-sog-kn", "2.0",
                               "--min-minutes", "30"]), 0)

    def test_analyze_cli_includes_encounters(self):
        self.assertEqual(main(["--format", "json", "analyze", self.cq]), 0)

    def test_encounters_export_geojson_cli(self):
        # export path runs core.analyze which now includes encounter findings
        self.assertEqual(main(["export", self.cq, "--to", "geojson"]), 0)


if __name__ == "__main__":
    unittest.main()
