"""Tests for the pattern-of-life / correlation layer (maritimeint.patterns).

Covers gap-timeline reconstruction, STS-transfer scoring (multi-signal fusion),
per-vessel pattern-of-life, the combined analyze_patterns report, and CLI wiring.
No network. Standard library only. Every fixture is synthetic and deterministic.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages  # noqa: E402
from maritimeint import patterns as P  # noqa: E402
from maritimeint.cli import main  # noqa: E402


def _hours(h, m=0):
    return f"2026-01-04T{h:02d}:{m:02d}:00Z"


def _repeat_dark_vessel():
    """One vessel that goes dark three separate times (each > 6 h)."""
    recs = []
    # active, then 8h dark, active, then 10h dark, active, then 7h dark, active
    schedule = [0, 1, 9, 10, 20, 21, 28]
    lat = 25.0
    for k, h in enumerate(schedule):
        recs.append({"mmsi": "DARK1", "timestamp": _hours(h % 24) if h < 24 else
                     f"2026-01-05T{(h - 24):02d}:00:00Z",
                     "lat": lat + 0.5 * k, "lon": 55.0 + 0.5 * k, "name": "SHADOW RUNNER"})
    return parse_messages(recs)


def _hm(minute_offset):
    """Timestamp `minute_offset` minutes after 2026-01-04T08:00Z."""
    total = 8 * 60 + minute_offset
    return f"2026-01-04T{total // 60:02d}:{total % 60:02d}:00Z"


def _sts_scene():
    """A loiter + dark + rendezvous stack: two vessels meet, one had gone dark and
    the other loitered around the same window."""
    recs = []
    # BUYER loiters in place from 08:00 through 17:30 at 25.0, 55.0
    for k in range(20):
        recs.append({"mmsi": "BUYER", "timestamp": _hm(k * 30),
                     "lat": 25.0, "lon": 55.0, "name": "BUYER", "sog": 0.1, "cog": 0})
    # SELLER last seen at 08:00 far away, then goes dark 8 h, reappearing alongside
    # BUYER at 16:00 and sitting there through 17:30 (the rendezvous window).
    recs.append({"mmsi": "SELLER", "timestamp": _hm(0), "lat": 26.0, "lon": 56.0,
                 "name": "SELLER", "sog": 10, "cog": 200})
    for k in range(4):
        recs.append({"mmsi": "SELLER", "timestamp": _hm(8 * 60 + k * 30),
                     "lat": 25.0, "lon": 55.003, "name": "SELLER", "sog": 0.1, "cog": 0})
    return parse_messages(recs)


class TestGapTimeline(unittest.TestCase):
    def test_repeat_dark_flagged(self):
        tl = P.gap_timeline(_repeat_dark_vessel())
        self.assertEqual(len(tl), 1)
        self.assertEqual(tl[0]["mmsi"], "DARK1")

    def test_multiple_windows_counted(self):
        tl = P.gap_timeline(_repeat_dark_vessel())
        self.assertGreaterEqual(tl[0]["dark_events"], 2)

    def test_windows_ordered(self):
        tl = P.gap_timeline(_repeat_dark_vessel())
        ws = tl[0]["windows"]
        self.assertEqual([w["dark_from"] for w in ws],
                         sorted(w["dark_from"] for w in ws))

    def test_total_and_longest(self):
        tl = P.gap_timeline(_repeat_dark_vessel())
        self.assertGreaterEqual(tl[0]["total_dark_hours"], tl[0]["longest_dark_hours"])

    def test_repeat_dark_high_severity(self):
        tl = P.gap_timeline(_repeat_dark_vessel())
        self.assertEqual(tl[0]["severity"], "high")  # >= 3 events

    def test_no_gaps_empty(self):
        recs = parse_messages([
            {"mmsi": "A", "timestamp": _hours(0), "lat": 1.0, "lon": 1.0, "name": "A"},
            {"mmsi": "A", "timestamp": _hours(1), "lat": 1.1, "lon": 1.0, "name": "A"},
        ])
        self.assertEqual(P.gap_timeline(recs), [])

    def test_drift_speed_computed(self):
        tl = P.gap_timeline(_repeat_dark_vessel())
        self.assertIn("reappear_drift_kn", tl[0]["windows"][0])


class TestStsScore(unittest.TestCase):
    def test_scene_scored(self):
        sts = P.sts_transfer_score(_sts_scene())
        self.assertGreaterEqual(len(sts), 1)

    def test_score_reflects_corroboration(self):
        sts = P.sts_transfer_score(_sts_scene())
        # rendezvous base (2) + loiter (2) + dark (2) should push above the bare anchor
        self.assertGreaterEqual(max(s["score"] for s in sts), 4)

    def test_evidence_listed(self):
        sts = P.sts_transfer_score(_sts_scene())
        top = max(sts, key=lambda s: s["score"])
        self.assertTrue(top["evidence"])

    def test_high_severity_when_stacked(self):
        sts = P.sts_transfer_score(_sts_scene())
        self.assertTrue(any(s["severity"] == "high" for s in sts))

    def test_no_meetings_no_candidates(self):
        recs = parse_messages([
            {"mmsi": "A", "timestamp": _hours(0), "lat": 1.0, "lon": 1.0, "name": "A"},
            {"mmsi": "B", "timestamp": _hours(0), "lat": 40.0, "lon": 40.0, "name": "B"},
        ])
        self.assertEqual(P.sts_transfer_score(recs), [])


class TestPatternOfLife(unittest.TestCase):
    def _vessel(self):
        recs = []
        for k in range(6):
            recs.append({"mmsi": "POL1", "timestamp": _hours(6 + k),
                         "lat": 25.0 + 0.05 * k, "lon": 55.0 + 0.05 * k,
                         "name": "ROUTINE", "sog": 10 + k})
        return parse_messages(recs)

    def test_one_record_per_vessel(self):
        pol = P.pattern_of_life(self._vessel())
        self.assertEqual(len(pol), 1)

    def test_bbox_and_centroid(self):
        pol = P.pattern_of_life(self._vessel())[0]
        self.assertEqual(len(pol["bbox"]), 4)
        self.assertEqual(len(pol["centroid"]), 2)

    def test_active_hours(self):
        pol = P.pattern_of_life(self._vessel())[0]
        self.assertEqual(pol["active_hours_utc"], [6, 7, 8, 9, 10, 11])

    def test_speed_stats(self):
        pol = P.pattern_of_life(self._vessel())[0]
        self.assertGreater(pol["max_sog_kn"], 0)
        self.assertGreater(pol["mean_sog_kn"], 0)

    def test_span_hours(self):
        pol = P.pattern_of_life(self._vessel())[0]
        self.assertAlmostEqual(pol["span_hours"], 5.0, places=1)

    def test_dark_and_loiter_counts_present(self):
        pol = P.pattern_of_life(self._vessel())[0]
        self.assertIn("dark_events", pol)
        self.assertIn("loiter_events", pol)


class TestAnalyzePatterns(unittest.TestCase):
    def test_report_shape(self):
        rep = P.analyze_patterns(_sts_scene())
        self.assertEqual(rep["mode"], "patterns")
        self.assertIn("finding_counts", rep)
        self.assertIn("findings", rep)

    def test_counts_present(self):
        rep = P.analyze_patterns(_sts_scene())
        for k in ("gap_timeline", "sts_candidate", "pattern_of_life"):
            self.assertIn(k, rep["finding_counts"])

    def test_empty_input(self):
        rep = P.analyze_patterns(parse_messages([]))
        self.assertEqual(rep["messages"], 0)
        self.assertEqual(rep["findings"], [])

    def test_zone_annotation(self):
        from maritimeint import zones as Z
        zs = Z.parse_zones([{"name": "MeetZone", "kind": "eez",
                             "center": [55.0, 25.0], "radius_nm": 50.0}])
        rep = P.analyze_patterns(_sts_scene(), zones=zs)
        pol = [f for f in rep["findings"] if f["type"] == "pattern_of_life"]
        # at least the BUYER at 25,55 should tag the zone via its centroid
        self.assertTrue(any("MeetZone" in f.get("zones", []) for f in pol))


class TestPatternsCLI(unittest.TestCase):
    @classmethod
    def _write(cls, msgs):
        recs = [m.as_record() for m in msgs]
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"messages": recs}, fh)
        return path

    def setUp(self):
        self.scene = self._write(_sts_scene())
        self.dark = self._write(_repeat_dark_vessel())
        self._paths = [self.scene, self.dark]

    def tearDown(self):
        for p in self._paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_gap_timeline_cli(self):
        self.assertEqual(main(["gap-timeline", self.dark]), 0)

    def test_sts_cli(self):
        self.assertEqual(main(["--format", "json", "sts", self.scene]), 0)

    def test_pattern_of_life_cli(self):
        self.assertEqual(main(["pattern-of-life", self.scene]), 0)

    def test_patterns_cli_json(self):
        self.assertEqual(main(["--format", "json", "patterns", self.scene]), 0)

    def test_patterns_cli_table(self):
        self.assertEqual(main(["patterns", self.scene]), 0)


if __name__ == "__main__":
    unittest.main()
