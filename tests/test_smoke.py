"""Smoke tests for MARITIMEINT. No network. Standard library only."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint import (  # noqa: E402
    TOOL_NAME,
    TOOL_VERSION,
    parse_messages,
    haversine_nm,
    detect_gaps,
    detect_speed_jumps,
    detect_loitering,
    detect_spoofing,
    detect_rendezvous,
    analyze,
)
from maritimeint.cli import main  # noqa: E402

DEMO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "demos", "01-basic", "feed.json",
)


def _load():
    with open(DEMO, encoding="utf-8") as fh:
        return parse_messages(json.load(fh)["messages"])


class TestMeta(unittest.TestCase):
    def test_meta(self):
        self.assertEqual(TOOL_NAME, "maritimeint")
        self.assertTrue(TOOL_VERSION)


class TestGeo(unittest.TestCase):
    def test_haversine_zero(self):
        self.assertAlmostEqual(haversine_nm(10, 20, 10, 20), 0.0, places=6)

    def test_haversine_known(self):
        # ~1 degree of latitude ~= 60 nm
        d = haversine_nm(0, 0, 1, 0)
        self.assertTrue(59 < d < 61, d)


class TestDetectors(unittest.TestCase):
    def setUp(self):
        self.msgs = _load()

    def test_parse_sorted(self):
        self.assertEqual(len(self.msgs), 10)

    def test_gap(self):
        gaps = detect_gaps(self.msgs, gap_hours=6.0)
        self.assertTrue(any(g["mmsi"] == "477123456" for g in gaps))

    def test_speed_jump(self):
        jumps = detect_speed_jumps(self.msgs)
        self.assertTrue(any(j["mmsi"] == "636099887" for j in jumps))

    def test_loiter(self):
        loiter = detect_loitering(self.msgs, radius_nm=2.0, min_hours=3.0)
        self.assertTrue(loiter)

    def test_spoof_identity(self):
        spoof = detect_spoofing(self.msgs)
        self.assertTrue(any(s["type"] == "identity_conflict"
                            and s["mmsi"] == "636099887" for s in spoof))

    def test_rendezvous(self):
        rdv = detect_rendezvous(self.msgs)
        self.assertTrue(rdv)
        pair = set(rdv[0]["vessels"])
        self.assertEqual(pair, {"477123456", "352987654"})

    def test_analyze(self):
        rep = analyze(self.msgs)
        self.assertEqual(rep["vessels_tracked"], 3)
        self.assertTrue(rep["risk_ranking"])
        self.assertEqual(rep["messages"], 10)


class TestCLI(unittest.TestCase):
    def test_analyze_json(self):
        rc = main(["--format", "json", "analyze", DEMO])
        self.assertEqual(rc, 0)

    def test_analyze_table(self):
        rc = main(["analyze", DEMO])
        self.assertEqual(rc, 0)

    def test_missing_file(self):
        rc = main(["analyze", "/no/such/feed.json"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
