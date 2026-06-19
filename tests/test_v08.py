"""Tests for the v0.8 layers: dark-rendezvous, GPS anomalies, zones, port-calls.

No network. Standard library only.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import (  # noqa: E402
    parse_messages,
    detect_dark_rendezvous,
    detect_gps_anomalies,
    analyze,
)
from maritimeint import zones as Z  # noqa: E402
from maritimeint import ports as P  # noqa: E402
from maritimeint.cli import main  # noqa: E402


def _circle(mmsi, clat, clon, radius_nm=0.5, n=9, start_hour=0):
    """n AIS points stepping a full loop around (clat, clon)."""
    deg = radius_nm / 60.0
    out = []
    for k in range(n):
        ang = math.radians(k * (360.0 / (n - 1)))
        lat = clat + deg * math.cos(ang)
        lon = clon + deg * math.sin(ang) / math.cos(math.radians(clat))
        out.append({"mmsi": mmsi, "timestamp": f"2026-01-04T{start_hour + k:02d}:00:00Z",
                    "lat": round(lat, 6), "lon": round(lon, 6), "name": "DRIFTER"})
    return out


class TestDarkRendezvous(unittest.TestCase):
    def setUp(self):
        recs = [
            # A goes dark for 8h around (26.0, 52.0)
            {"mmsi": "A1", "timestamp": "2026-01-04T00:00:00Z", "lat": 26.0, "lon": 52.0, "name": "DARK TANKER"},
            {"mmsi": "A1", "timestamp": "2026-01-04T08:00:00Z", "lat": 26.1, "lon": 52.1, "name": "DARK TANKER"},
            # B keeps reporting near A's vanish point during the window
            {"mmsi": "B1", "timestamp": "2026-01-04T03:00:00Z", "lat": 26.02, "lon": 52.02, "name": "LIGHTER"},
            {"mmsi": "B1", "timestamp": "2026-01-04T04:00:00Z", "lat": 26.01, "lon": 52.01, "name": "LIGHTER"},
            # C is far away, should not match
            {"mmsi": "C1", "timestamp": "2026-01-04T03:30:00Z", "lat": 10.0, "lon": 10.0, "name": "FARAWAY"},
        ]
        self.msgs = parse_messages(recs)

    def test_dark_rendezvous_found(self):
        f = detect_dark_rendezvous(self.msgs, gap_hours=6.0, proximity_nm=5.0)
        self.assertEqual(len(f), 1)
        self.assertEqual(set(f[0]["vessels"]), {"A1", "B1"})
        self.assertEqual(f[0]["dark_vessel"], "A1")
        self.assertGreaterEqual(f[0]["present_reports"], 2)

    def test_far_vessel_excluded(self):
        f = detect_dark_rendezvous(self.msgs)
        self.assertTrue(all("C1" not in x["vessels"] for x in f))

    def test_in_analyze(self):
        rep = analyze(self.msgs)
        self.assertEqual(rep["finding_counts"]["dark_rendezvous"], 1)


class TestGpsAnomalies(unittest.TestCase):
    def test_circle_spoof(self):
        msgs = parse_messages(_circle("SPOOF1", 25.0, 55.0, radius_nm=0.5, n=9))
        f = detect_gps_anomalies(msgs)
        circ = [x for x in f if x["type"] == "circle_spoof"]
        self.assertEqual(len(circ), 1)
        self.assertGreaterEqual(circ[0]["arc_degrees"], 300.0)
        self.assertLessEqual(circ[0]["radius_nm"], 3.0)

    def test_no_circle_for_straight_line(self):
        recs = [{"mmsi": "LINE", "timestamp": f"2026-01-04T{h:02d}:00:00Z",
                 "lat": 20.0 + 0.05 * h, "lon": 40.0, "name": "STRAIGHT"} for h in range(10)]
        f = detect_gps_anomalies(parse_messages(recs))
        self.assertFalse([x for x in f if x["type"] == "circle_spoof"])

    def test_gps_jamming(self):
        recs = []
        for i, m in enumerate(("J1", "J2", "J3", "J4")):
            recs.append({"mmsi": m, "timestamp": f"2026-01-04T12:{i:02d}:00Z",
                         "lat": 40.1234, "lon": 50.1234, "name": f"V{m}"})
        f = detect_gps_anomalies(parse_messages(recs))
        jam = [x for x in f if x["type"] == "gps_jamming"]
        self.assertEqual(len(jam), 1)
        self.assertEqual(jam[0]["vessel_count"], 4)


class TestZones(unittest.TestCase):
    def setUp(self):
        self.zones = Z.parse_zones([
            {"name": "Test EEZ", "kind": "eez",
             "polygon": [[50.0, 25.0], [55.0, 25.0], [55.0, 30.0], [50.0, 30.0]]},
            {"name": "Test Port", "kind": "sanctioned_port",
             "center": [52.0, 27.0], "radius_nm": 10.0},
        ])

    def test_point_in_polygon(self):
        self.assertEqual(Z.zones_for_point(27.0, 52.0, self.zones),
                         ["Test EEZ", "Test Port"])  # inside both
        self.assertEqual(Z.zones_for_point(0.0, 0.0, self.zones), [])

    def test_geojson_feature_collection(self):
        gj = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": "GJ Zone", "kind": "exclusion"},
             "geometry": {"type": "Polygon",
                          "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]]}}]}
        zs = Z.parse_zones(gj)
        self.assertEqual(zs[0].name, "GJ Zone")
        self.assertTrue(zs[0].contains(1.0, 1.0))

    def test_zone_transit(self):
        recs = [
            {"mmsi": "T1", "timestamp": "2026-01-04T00:00:00Z", "lat": 27.0, "lon": 52.0, "name": "X"},
            {"mmsi": "T1", "timestamp": "2026-01-04T03:00:00Z", "lat": 27.05, "lon": 52.05, "name": "X"},
            {"mmsi": "T1", "timestamp": "2026-01-04T06:00:00Z", "lat": 10.0, "lon": 10.0, "name": "X"},
        ]
        f = Z.detect_zone_transits(parse_messages(recs), self.zones)
        port = [x for x in f if x["zone"] == "Test Port"]
        self.assertEqual(len(port), 1)
        self.assertAlmostEqual(port[0]["dwell_hours"], 3.0, places=1)
        self.assertEqual(port[0]["severity"], "high")

    def test_annotate_findings(self):
        findings = [{"type": "ais_gap", "from": [27.0, 52.0], "to": [10.0, 10.0]}]
        Z.annotate_findings(findings, self.zones)
        self.assertIn("Test Port", findings[0]["zones"])

    def test_analyze_with_zones(self):
        recs = [
            {"mmsi": "A1", "timestamp": "2026-01-04T00:00:00Z", "lat": 27.0, "lon": 52.0, "name": "T"},
            {"mmsi": "A1", "timestamp": "2026-01-04T09:00:00Z", "lat": 27.0, "lon": 52.0, "name": "T"},
        ]
        rep = analyze(parse_messages(recs), zones=self.zones)
        gap = next(f for f in rep["findings"] if f["type"] == "ais_gap")
        self.assertIn("Test Port", gap.get("zones", []))


class TestPortCalls(unittest.TestCase):
    def setUp(self):
        # Kharg Island (sanctioned) then Singapore (normal)
        recs = []
        for h in range(3):
            recs.append({"mmsi": "P1", "timestamp": f"2026-01-04T0{h}:00:00Z",
                         "lat": 29.23, "lon": 50.32, "name": "GREY TANKER"})
        for h in range(3):
            recs.append({"mmsi": "P1", "timestamp": f"2026-01-1{h}T00:00:00Z",
                         "lat": 1.264, "lon": 103.840, "name": "GREY TANKER"})
        self.msgs = parse_messages(recs)

    def test_detect_calls(self):
        calls = P.detect_port_calls(self.msgs)
        ports = {c["port"] for c in calls}
        self.assertIn("Kharg Island", ports)
        self.assertIn("Singapore", ports)
        kharg = next(c for c in calls if c["port"] == "Kharg Island")
        self.assertEqual(kharg["risk"], "sanctioned")
        self.assertEqual(kharg["severity"], "high")

    def test_itinerary(self):
        calls = P.detect_port_calls(self.msgs)
        its = P.sequence_itineraries(calls)
        self.assertEqual(len(its), 1)
        it = its[0]
        self.assertEqual(it["mmsi"], "P1")
        self.assertIn("Kharg Island", it["risk_ports_visited"])
        self.assertEqual(it["calls"], ["Kharg Island", "Singapore"])
        self.assertTrue(it["legs"][0]["touches_risk_port"])

    def test_custom_registry_load(self):
        import json, tempfile
        data = [{"name": "Custom", "country": "XX", "lat": 5.0, "lon": 5.0,
                 "radius_nm": 10, "risk": "high"}]
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        try:
            ports = P.load_ports(path)
            self.assertEqual(ports[0]["name"], "Custom")
            self.assertEqual(ports[0]["risk"], "high")
        finally:
            os.unlink(path)


class TestCLIv08(unittest.TestCase):
    def setUp(self):
        import json, tempfile
        recs = [
            {"mmsi": "A1", "timestamp": "2026-01-04T00:00:00Z", "lat": 26.0, "lon": 52.0, "name": "DARK"},
            {"mmsi": "A1", "timestamp": "2026-01-04T08:00:00Z", "lat": 26.1, "lon": 52.1, "name": "DARK"},
            {"mmsi": "B1", "timestamp": "2026-01-04T03:00:00Z", "lat": 26.02, "lon": 52.02, "name": "LIGHTER"},
        ]
        fd, self.feed = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"messages": recs}, fh)
        zones = [{"name": "Z", "kind": "eez",
                  "polygon": [[51.0, 25.0], [53.0, 25.0], [53.0, 27.0], [51.0, 27.0]]}]
        fd2, self.zonef = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd2, "w", encoding="utf-8") as fh:
            json.dump(zones, fh)

    def tearDown(self):
        os.unlink(self.feed)
        os.unlink(self.zonef)

    def test_dark_rendezvous_cli(self):
        self.assertEqual(main(["--format", "json", "dark-rendezvous", self.feed]), 0)

    def test_gps_cli(self):
        self.assertEqual(main(["gps", self.feed]), 0)

    def test_zones_cli(self):
        self.assertEqual(main(["zones", self.feed, "--zones", self.zonef]), 0)

    def test_port_calls_cli(self):
        self.assertEqual(main(["port-calls", self.feed, "--itinerary"]), 0)

    def test_analyze_with_zones_cli(self):
        self.assertEqual(main(["--format", "json", "analyze", self.feed, "--zones", self.zonef]), 0)


if __name__ == "__main__":
    unittest.main()
