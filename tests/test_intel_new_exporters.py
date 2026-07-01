"""Tests for the new intel exporters: CoT (Cursor-on-Target) and KML timeline.

The existing GeoJSON/KML/STIX/CSV exporters are covered elsewhere; this focuses on
the additive `to_cot` / `to_kml_timeline` formats and their CLI wiring. Standard
library only; XML is validated by parsing it back with ElementTree.
"""

import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages, analyze  # noqa: E402
from maritimeint import intel  # noqa: E402
from maritimeint.cli import main  # noqa: E402


def _geo_result():
    """A result whose findings carry coordinates + start/end (a zone transit)."""
    return {
        "findings": [
            {"type": "ais_gap", "mmsi": "111", "name": "ALPHA", "severity": "high",
             "dark_from": "2026-01-04T00:00:00Z", "dark_to": "2026-01-04T08:00:00Z",
             "from": [25.0, 55.0], "to": [26.0, 56.0]},
            {"type": "loitering", "mmsi": "222", "name": "BRAVO", "severity": "medium",
             "start": "2026-01-04T01:00:00Z", "end": "2026-01-04T05:00:00Z",
             "center": [24.5, 54.5]},
            {"type": "identity_conflict", "mmsi": "333", "severity": "high"},  # no coords
        ]
    }


class TestCoT(unittest.TestCase):
    def test_wellformed_xml(self):
        root = ET.fromstring(intel.to_cot(_geo_result()))
        self.assertEqual(root.tag, "events")

    def test_one_event_per_geo_finding(self):
        root = ET.fromstring(intel.to_cot(_geo_result()))
        # two of three findings carry coordinates
        self.assertEqual(len(root.findall("event")), 2)

    def test_event_has_point(self):
        root = ET.fromstring(intel.to_cot(_geo_result()))
        for ev in root.findall("event"):
            pt = ev.find("point")
            self.assertIsNotNone(pt)
            self.assertIn("lat", pt.attrib)
            self.assertIn("lon", pt.attrib)

    def test_affiliation_never_hostile(self):
        root = ET.fromstring(intel.to_cot(_geo_result()))
        for ev in root.findall("event"):
            # unknown affiliation only; this tool never asserts hostile ("a-h-")
            self.assertFalse(ev.attrib["type"].startswith("a-h-"))
            self.assertEqual(ev.attrib["type"], "a-u-S")

    def test_remarks_present(self):
        root = ET.fromstring(intel.to_cot(_geo_result()))
        ev = root.find("event")
        self.assertIsNotNone(ev.find("detail/remarks"))

    def test_empty_findings(self):
        root = ET.fromstring(intel.to_cot({"findings": []}))
        self.assertEqual(root.findall("event"), [])


class TestKmlTimeline(unittest.TestCase):
    def test_wellformed(self):
        kml = intel.to_kml_timeline(_geo_result())
        self.assertIn("<kml", kml)
        self.assertIn("</kml>", kml)

    def test_timespan_for_start_end(self):
        kml = intel.to_kml_timeline(_geo_result())
        self.assertIn("<TimeSpan>", kml)
        self.assertIn("2026-01-04T00:00:00Z", kml)

    def test_parseable_xml(self):
        # strip default namespace for a simple structural check
        kml = intel.to_kml_timeline(_geo_result())
        root = ET.fromstring(kml)
        self.assertTrue(root.tag.endswith("kml"))

    def test_skips_coordless(self):
        kml = intel.to_kml_timeline(_geo_result())
        # identity_conflict (333) has no coords -> not placed
        self.assertNotIn("333", kml)


class TestExportRegistryAndCLI(unittest.TestCase):
    def test_export_dispatch_cot(self):
        out = intel.export(_geo_result(), "cot")
        self.assertIn("<events>", out)

    def test_export_dispatch_kml_timeline(self):
        out = intel.export(_geo_result(), "kml-timeline")
        self.assertIn("<kml", out)

    def test_unknown_format_lists_new_ones(self):
        with self.assertRaises(ValueError) as ctx:
            intel.export(_geo_result(), "nope")
        msg = str(ctx.exception)
        self.assertIn("cot", msg)
        self.assertIn("kml-timeline", msg)

    def test_cli_export_cot(self):
        recs = [
            {"mmsi": "111", "timestamp": "2026-01-04T00:00:00Z", "lat": 25.0,
             "lon": 55.0, "name": "A"},
            {"mmsi": "111", "timestamp": "2026-01-04T10:00:00Z", "lat": 26.0,
             "lon": 56.0, "name": "A"},
        ]
        msgs = parse_messages(recs)
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"messages": [m.as_record() for m in msgs]}, fh)
        try:
            self.assertEqual(main(["export", path, "--to", "cot"]), 0)
            self.assertEqual(main(["export", path, "--to", "kml-timeline"]), 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
