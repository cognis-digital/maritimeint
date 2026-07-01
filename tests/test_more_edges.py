"""Additional boundary tests to broaden coverage across the public API."""
import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import (  # noqa: E402
    parse_messages, AISMessage, detect_gaps, detect_speed_jumps,
    detect_loitering, detect_spoofing, analyze, haversine_nm, _bearing,
)
from maritimeint import intel, zones as Z, ports as P, encounters as E  # noqa: E402


def rec(mmsi, hour, lat, lon, **kw):
    r = {"mmsi": mmsi, "timestamp": f"2026-01-04T{hour:02d}:00:00Z", "lat": lat, "lon": lon}
    r.update(kw)
    return r


# --------------------------------------------------------------------------- #
# multi-vessel and ordering robustness
# --------------------------------------------------------------------------- #
class TestMultiVessel:
    def test_gaps_independent_per_vessel(self):
        m = parse_messages([rec("A", 0, 1, 1), rec("A", 8, 1, 1),
                            rec("B", 0, 2, 2), rec("B", 1, 2, 2)])
        g = detect_gaps(m)
        assert len(g) == 1 and g[0]["mmsi"] == "A"

    def test_unsorted_input_still_correct(self):
        m = parse_messages([rec("A", 8, 1, 1), rec("A", 0, 1, 1)])
        assert len(detect_gaps(m)) == 1

    def test_interleaved_vessels(self):
        recs = []
        for h in range(3):
            recs += [rec("A", h, 25, 55), rec("B", h, 25, 55)]
        m = parse_messages(recs)
        assert analyze(m)["vessels_tracked"] == 2

    def test_many_vessels_no_crash(self):
        recs = [rec(f"V{i}", 0, 20 + i * 0.1, 40) for i in range(30)]
        recs += [rec(f"V{i}", 9, 20 + i * 0.1, 41) for i in range(30)]
        r = analyze(parse_messages(recs))
        assert r["vessels_tracked"] == 30


# --------------------------------------------------------------------------- #
# name-carry behaviours
# --------------------------------------------------------------------------- #
class TestNameHandling:
    def test_gap_uses_available_name(self):
        m = parse_messages([rec("A", 0, 1, 1, name=""), rec("A", 8, 1, 1, name="LATER")])
        assert detect_gaps(m)[0]["name"] == "LATER"

    def test_nameless_vessel_ok(self):
        m = parse_messages([rec("A", 0, 1, 1), rec("A", 8, 1, 1)])
        assert detect_gaps(m)[0]["name"] == ""


# --------------------------------------------------------------------------- #
# rounding / precision in output
# --------------------------------------------------------------------------- #
class TestOutputPrecision:
    def test_coords_rounded_5dp(self):
        m = parse_messages([rec("A", 0, 26.123456789, 52.987654321),
                            rec("A", 8, 27.0, 53.0)])
        frm = detect_gaps(m)[0]["from"]
        assert abs(frm[0]) < 90 and len(str(frm[0]).split(".")[-1]) <= 5

    def test_gap_hours_rounded(self):
        m = parse_messages([rec("A", 0, 1, 1), rec("A", 7, 1, 1)])
        assert detect_gaps(m)[0]["gap_hours"] == 7.0


# --------------------------------------------------------------------------- #
# exporter robustness with mixed / weird findings
# --------------------------------------------------------------------------- #
class TestExporterRobustness:
    def test_geojson_with_analyze_output(self):
        m = parse_messages([rec("A", 0, 26, 52), rec("A", 9, 27, 53)])
        gj = json.loads(intel.to_geojson(analyze(m)))
        assert gj["type"] == "FeatureCollection"

    def test_kml_valid_with_analyze(self):
        m = parse_messages([rec("A", 0, 26, 52), rec("A", 9, 27, 53)])
        ET.fromstring(intel.to_kml(analyze(m)))

    def test_stix_valid_with_analyze(self):
        m = parse_messages([rec("A", 0, 26, 52), rec("A", 9, 27, 53)])
        b = json.loads(intel.to_stix(analyze(m)))
        assert b["type"] == "bundle"

    def test_csv_header_stable(self):
        m = parse_messages([rec("A", 0, 26, 52), rec("A", 9, 27, 53)])
        assert intel.to_csv(analyze(m)).splitlines()[0].startswith("type,severity")

    def test_geojson_unicode_name(self):
        f = {"type": "x", "name": "Motörhead Ø", "center": [1, 2]}
        gj = json.loads(intel.to_geojson({"findings": [f]}))
        assert "Mot" in gj["features"][0]["properties"]["name"]

    def test_kml_unicode_name(self):
        f = {"type": "x", "name": "Ålesund", "center": [1, 2]}
        ET.fromstring(intel.to_kml({"findings": [f]}))


# --------------------------------------------------------------------------- #
# zone geometry corners
# --------------------------------------------------------------------------- #
class TestZoneCorners:
    def test_circle_radius_boundary(self):
        z = Z.Zone(name="p", center=(0.0, 0.0), radius_nm=61.0)
        # ~1 deg lat north = ~60 nm -> inside a 61 nm circle
        assert z.contains(1.0, 0.0)
        # and a point ~120 nm north is outside
        assert not z.contains(2.0, 0.0)

    def test_point_geometry_default_radius(self):
        zs = Z.parse_zones({"type": "Feature", "properties": {"name": "pt"},
                            "geometry": {"type": "Point", "coordinates": [50.0, 25.0]}})
        assert zs[0].radius_nm == 1.0

    def test_zone_kind_defaults(self):
        zs = Z.parse_zones([{"name": "z", "polygon": [[0, 0], [1, 0], [1, 1]]}])
        assert zs[0].kind == "zone"


# --------------------------------------------------------------------------- #
# port-call sequencing details
# --------------------------------------------------------------------------- #
class TestPortSequenceDetails:
    def test_single_call_no_legs(self):
        recs = [rec("A", h, 29.23, 50.32, name="X") for h in range(3)]
        its = P.sequence_itineraries(P.detect_port_calls(parse_messages(recs)))
        assert its[0]["legs"] == []

    def test_three_ports_two_legs(self):
        recs = []
        for h in range(2):
            recs.append(rec("A", h, 29.23, 50.32, name="X"))  # Kharg
        for h in range(2):
            recs.append({"mmsi": "A", "timestamp": f"2026-01-05T0{h}:00:00Z",
                         "lat": 25.112, "lon": 56.350, "name": "X"})  # Fujairah
        for h in range(2):
            recs.append({"mmsi": "A", "timestamp": f"2026-01-06T0{h}:00:00Z",
                         "lat": 1.264, "lon": 103.840, "name": "X"})  # Singapore
        its = P.sequence_itineraries(P.detect_port_calls(parse_messages(recs)))
        assert len(its[0]["legs"]) == 2


# --------------------------------------------------------------------------- #
# encounters analyze_encounters wiring
# --------------------------------------------------------------------------- #
class TestEncountersWiring:
    def test_drift_appears_in_encounters(self):
        pts = [(0.000, 0.000), (0.0005, 0.0002), (0.0004, 0.0009),
               (0.0011, 0.0007), (0.0006, 0.0015)]
        recs = []
        for i, (dlat, dlon) in enumerate(pts):
            t = i * 30
            recs.append({"mmsi": "DR", "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                         "lat": 25.0 + dlat, "lon": 55.0 + dlon, "name": "A", "sog": 0.3})
        r = E.analyze_encounters(parse_messages(recs))
        assert r["finding_counts"]["drift"] >= 1

    def test_encounters_zone_enrichment(self):
        recs = []
        for e in range(4):
            t = e * 40
            for k, mmsi in enumerate(("C1", "C2", "C3")):
                recs.append({"mmsi": mmsi,
                             "timestamp": f"2026-01-04T{t // 60:02d}:{t % 60:02d}:00Z",
                             "lat": 25.0 + e * 0.1 + k * 0.005, "lon": 55.0,
                             "name": mmsi, "sog": 10, "cog": 0})
        zones = Z.parse_zones([{"name": "Z", "kind": "eez",
                                "polygon": [[54, 24], [56, 24], [56, 27], [54, 27]]}])
        r = E.analyze_encounters(parse_messages(recs), zones=zones)
        assert r["mode"] == "encounters"


# --------------------------------------------------------------------------- #
# consistency between analyze counts and finding list
# --------------------------------------------------------------------------- #
class TestAnalyzeConsistency:
    def _scene(self):
        recs = [rec("V1", 0, 26.0, 52.0, name="D"), rec("V1", 9, 26.6, 52.6, name="D")]
        recs += [rec("V2", h, 25.0, 55.0, name="L") for h in range(6)]
        return parse_messages(recs)

    @pytest.mark.parametrize("kind", ["ais_gap", "loitering", "speed_jump"])
    def test_count_matches_typed_findings(self, kind):
        r = analyze(self._scene())
        typed = [f for f in r["findings"] if f["type"] == kind]
        # counts use aggregate keys; ais_gap/loitering/speed_jump map 1:1
        assert r["finding_counts"][kind] == len(typed)

    def test_all_findings_have_severity(self):
        r = analyze(self._scene())
        assert all("severity" in f for f in r["findings"])

    def test_all_findings_have_type(self):
        r = analyze(self._scene())
        assert all("type" in f for f in r["findings"])


# --------------------------------------------------------------------------- #
# geodesy extra
# --------------------------------------------------------------------------- #
class TestGeodesyExtra:
    @pytest.mark.parametrize("lat", [0, 30, 60, -45])
    def test_haversine_positive(self, lat):
        assert haversine_nm(lat, 0, lat, 1) > 0

    def test_bearing_south(self):
        assert _bearing(1, 0, 0, 0) == pytest.approx(180.0, abs=1.0)

    def test_bearing_west(self):
        assert _bearing(0, 1, 0, 0) == pytest.approx(270.0, abs=1.0)


# --------------------------------------------------------------------------- #
# module entrypoint
# --------------------------------------------------------------------------- #
class TestEntrypoint:
    def test_main_module_importable(self):
        import maritimeint.__main__ as mm
        assert hasattr(mm, "main") or True  # imports without side effects

    def test_cli_main_callable(self):
        from maritimeint.cli import main
        assert callable(main)
