"""Tests for the fleet / network analytics layer (maritimeint.fleet).

Covers the contact graph, fleet-ring components, flag-hopping, identity rings,
the combined analyze_fleet report, the new CLI subcommands, and export round-trips.
No network. Standard library only. Every fixture is synthetic and deterministic.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages  # noqa: E402
from maritimeint import fleet as F  # noqa: E402
from maritimeint import intel  # noqa: E402
from maritimeint.cli import main  # noqa: E402


def _ts(minute_offset):
    total = 12 * 60 + minute_offset
    return f"2026-01-04T{total // 60 % 24:02d}:{total % 60:02d}:00Z"


def _rendezvous_pair():
    """Two vessels sitting alongside each other for well over the min window."""
    recs = []
    for k in range(6):
        recs.append({"mmsi": "111111111", "timestamp": _ts(k * 15), "lat": 25.0,
                     "lon": 55.0, "name": "ALPHA", "sog": 0.1, "cog": 0})
        recs.append({"mmsi": "222222222", "timestamp": _ts(k * 15), "lat": 25.0,
                     "lon": 55.003, "name": "BRAVO", "sog": 0.1, "cog": 0})
    return parse_messages(recs)


def _convoy(members=("V1", "V2", "V3")):
    recs = []
    for k in range(5):
        lat = 10.0 + 0.1 * k
        for i, m in enumerate(members):
            recs.append({"mmsi": m, "timestamp": _ts(k * 60), "lat": lat,
                         "lon": 30.0 + 0.02 * i, "name": m, "sog": 11, "cog": 0})
    return parse_messages(recs)


class TestMidFlag(unittest.TestCase):
    def test_mid_extracted(self):
        self.assertEqual(F.mid_of("273123456"), "273")
        self.assertEqual(F.mid_of("636987654"), "636")

    def test_mid_short_mmsi(self):
        self.assertEqual(F.mid_of("42"), "")

    def test_flag_known(self):
        self.assertEqual(F.flag_of("273000000"), "Russia")
        self.assertEqual(F.flag_of("636000000"), "Liberia")

    def test_flag_unknown_mid_is_structural(self):
        # an MID not in the table still yields a distinct, comparable flag token
        self.assertTrue(F.flag_of("999000000").startswith("MID-"))

    def test_flag_empty(self):
        self.assertEqual(F.flag_of(""), "unknown")


class TestContactNetwork(unittest.TestCase):
    def test_rendezvous_makes_edge(self):
        net = F.contact_network(_rendezvous_pair())
        self.assertEqual(net["type"], "contact_network")
        self.assertEqual(len(net["nodes"]), 2)
        self.assertEqual(len(net["edges"]), 1)
        self.assertEqual(set(net["edges"][0]["vessels"]), {"111111111", "222222222"})

    def test_edge_carries_interaction(self):
        net = F.contact_network(_rendezvous_pair())
        self.assertIn("rendezvous", net["edges"][0]["interactions"])

    def test_node_degree(self):
        net = F.contact_network(_rendezvous_pair())
        self.assertTrue(all(n["degree"] == 1 for n in net["nodes"]))

    def test_node_has_flag(self):
        net = F.contact_network(_rendezvous_pair())
        self.assertTrue(all("flag" in n for n in net["nodes"]))

    def test_isolated_vessels_no_edges(self):
        recs = parse_messages([
            {"mmsi": "A", "timestamp": _ts(0), "lat": 0.0, "lon": 0.0, "name": "A"},
            {"mmsi": "B", "timestamp": _ts(0), "lat": 40.0, "lon": 40.0, "name": "B"},
        ])
        net = F.contact_network(recs)
        self.assertEqual(net["edges"], [])

    def test_convoy_makes_clique_edges(self):
        net = F.contact_network(_convoy())
        # a 3-vessel convoy yields 3 pairwise edges
        self.assertEqual(len(net["edges"]), 3)


class TestFleetRings(unittest.TestCase):
    def test_pair_ring(self):
        rings = F.fleet_rings(_rendezvous_pair())
        self.assertEqual(len(rings), 1)
        self.assertEqual(rings[0]["vessel_count"], 2)

    def test_convoy_ring(self):
        rings = F.fleet_rings(_convoy())
        self.assertEqual(len(rings), 1)
        self.assertEqual(rings[0]["vessel_count"], 3)
        self.assertEqual(rings[0]["edge_count"], 3)

    def test_min_size_filters(self):
        self.assertEqual(F.fleet_rings(_rendezvous_pair(), min_size=3), [])

    def test_ring_lists_interactions(self):
        rings = F.fleet_rings(_convoy())
        self.assertIn("convoy", rings[0]["interactions"])

    def test_no_interactions_no_rings(self):
        recs = parse_messages([
            {"mmsi": "A", "timestamp": _ts(0), "lat": 0.0, "lon": 0.0, "name": "A"},
            {"mmsi": "B", "timestamp": _ts(0), "lat": 40.0, "lon": 40.0, "name": "B"},
        ])
        self.assertEqual(F.fleet_rings(recs), [])

    def test_multi_flag_flag(self):
        rings = F.fleet_rings(_rendezvous_pair())
        # ALPHA=111 (MID-111), BRAVO=222 (MID-222) -> two distinct flags
        self.assertTrue(rings[0]["multi_flag"])


class TestFlagHopping(unittest.TestCase):
    def _hopper(self):
        recs = []
        for mmsi in ("273123456", "636987654"):
            for k in range(2):
                recs.append({"mmsi": mmsi, "timestamp": _ts(k * 30),
                             "lat": 25.0 + k * 0.1, "lon": 55.0,
                             "name": "NEPTUNE STAR"})
        return parse_messages(recs)

    def test_detects_two_flags(self):
        f = F.flag_hopping(self._hopper())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["flag_count"], 2)
        self.assertEqual(set(f[0]["flags"]), {"Russia", "Liberia"})

    def test_single_flag_not_flagged(self):
        recs = parse_messages([
            {"mmsi": "273111111", "timestamp": _ts(0), "lat": 1.0, "lon": 1.0, "name": "X"},
            {"mmsi": "273222222", "timestamp": _ts(0), "lat": 2.0, "lon": 2.0, "name": "X"},
        ])
        self.assertEqual(F.flag_hopping(recs), [])

    def test_imo_keys_hull(self):
        recs = parse_messages([
            {"mmsi": "273111111", "timestamp": _ts(0), "lat": 1.0, "lon": 1.0, "name": "A"},
            {"mmsi": "636222222", "timestamp": _ts(0), "lat": 2.0, "lon": 2.0, "name": "B"},
        ])
        static = {"273111111": {"imo": "9111111"}, "636222222": {"imo": "9111111"}}
        f = F.flag_hopping(recs, static=static)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["hull"], "IMO 9111111")

    def test_three_flags_high_severity(self):
        recs = parse_messages([
            {"mmsi": "273111111", "timestamp": _ts(0), "lat": 1.0, "lon": 1.0, "name": "TRIPLE"},
            {"mmsi": "636222222", "timestamp": _ts(0), "lat": 2.0, "lon": 2.0, "name": "TRIPLE"},
            {"mmsi": "351333333", "timestamp": _ts(0), "lat": 3.0, "lon": 3.0, "name": "TRIPLE"},
        ])
        f = F.flag_hopping(recs)
        self.assertEqual(f[0]["severity"], "high")


class TestIdentityRings(unittest.TestCase):
    def test_name_clone(self):
        recs = parse_messages([
            {"mmsi": "111", "timestamp": _ts(0), "lat": 1.0, "lon": 1.0, "name": "GHOST"},
            {"mmsi": "222", "timestamp": _ts(0), "lat": 2.0, "lon": 2.0, "name": "GHOST"},
        ])
        f = F.identity_rings(recs)
        clones = [x for x in f if x["type"] == "name_clone"]
        self.assertEqual(len(clones), 1)
        self.assertEqual(clones[0]["mmsi_count"], 2)

    def test_mmsi_multiname(self):
        recs = parse_messages([
            {"mmsi": "111", "timestamp": _ts(0), "lat": 1.0, "lon": 1.0, "name": "NAME ONE"},
            {"mmsi": "111", "timestamp": _ts(30), "lat": 1.1, "lon": 1.0, "name": "NAME TWO"},
        ])
        f = F.identity_rings(recs)
        multi = [x for x in f if x["type"] == "mmsi_multiname"]
        self.assertEqual(len(multi), 1)
        self.assertEqual(multi[0]["name_count"], 2)

    def test_clean_identities_no_findings(self):
        recs = parse_messages([
            {"mmsi": "111", "timestamp": _ts(0), "lat": 1.0, "lon": 1.0, "name": "ONE"},
            {"mmsi": "222", "timestamp": _ts(0), "lat": 2.0, "lon": 2.0, "name": "TWO"},
        ])
        self.assertEqual(F.identity_rings(recs), [])


class TestAnalyzeFleet(unittest.TestCase):
    def test_report_shape(self):
        rep = F.analyze_fleet(_convoy())
        self.assertEqual(rep["mode"], "fleet")
        self.assertIn("network", rep)
        self.assertIn("finding_counts", rep)
        self.assertIn("network_graph", rep)

    def test_counts(self):
        rep = F.analyze_fleet(_convoy())
        self.assertEqual(rep["finding_counts"]["fleet_ring"], 1)

    def test_empty_input(self):
        rep = F.analyze_fleet(parse_messages([]))
        self.assertEqual(rep["messages"], 0)
        self.assertEqual(rep["findings"], [])

    def test_zone_annotation_passthrough(self):
        # fleet findings are relational (no coords) so zone tagging is a no-op but
        # must not raise
        from maritimeint import zones as Z
        zs = Z.parse_zones([{"name": "Z", "kind": "eez", "center": [30.0, 10.0],
                             "radius_nm": 50.0}])
        rep = F.analyze_fleet(_convoy(), zones=zs)
        self.assertIn("findings", rep)


class TestFleetCLI(unittest.TestCase):
    @classmethod
    def _write(cls, msgs):
        recs = [m.as_record() for m in msgs]
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"messages": recs}, fh)
        return path

    def setUp(self):
        self.conv = self._write(_convoy())
        self.rdv = self._write(_rendezvous_pair())
        self._paths = [self.conv, self.rdv]

    def tearDown(self):
        for p in self._paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_network_cli_table(self):
        self.assertEqual(main(["network", self.conv]), 0)

    def test_network_cli_json(self):
        self.assertEqual(main(["--format", "json", "network", self.conv]), 0)

    def test_rings_cli(self):
        self.assertEqual(main(["rings", self.conv]), 0)

    def test_rings_cli_min_size(self):
        self.assertEqual(main(["rings", self.conv, "--min-size", "5"]), 0)

    def test_flag_hopping_cli(self):
        self.assertEqual(main(["flag-hopping", self.rdv]), 0)

    def test_identity_cli(self):
        self.assertEqual(main(["identity", self.rdv]), 0)

    def test_fleet_cli(self):
        self.assertEqual(main(["--format", "json", "fleet", self.conv]), 0)

    def test_fleet_cli_table(self):
        self.assertEqual(main(["fleet", self.conv]), 0)


class TestFleetExports(unittest.TestCase):
    def test_fleet_findings_export_json(self):
        rep = F.analyze_fleet(_convoy())
        # relational findings carry no coords -> geojson features have null geometry
        gj = json.loads(intel.to_geojson(rep))
        self.assertEqual(gj["type"], "FeatureCollection")

    def test_fleet_findings_csv(self):
        rep = F.analyze_fleet(_convoy())
        csv_text = intel.to_csv(rep)
        self.assertIn("fleet_ring", csv_text)


if __name__ == "__main__":
    unittest.main()
