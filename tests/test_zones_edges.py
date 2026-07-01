"""Edge-case tests for maritimeint.zones (geofencing, transits, annotation)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages  # noqa: E402
from maritimeint import zones as Z  # noqa: E402
from maritimeint.zones import (  # noqa: E402
    Zone,
    parse_zones,
    zones_for_point,
    detect_zone_transits,
    annotate_findings,
    _point_in_ring,
)


def rec(mmsi, hour, lat, lon, **kw):
    r = {"mmsi": mmsi, "timestamp": f"2026-01-04T{hour:02d}:00:00Z", "lat": lat, "lon": lon}
    r.update(kw)
    return r


SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]  # (lon, lat)


class TestPointInRing:
    def test_inside(self):
        assert _point_in_ring(5, 5, SQUARE)

    def test_outside(self):
        assert not _point_in_ring(20, 20, SQUARE)

    def test_on_vertex_or_edge_counts_inside(self):
        assert _point_in_ring(0, 5, SQUARE)

    def test_degenerate_ring(self):
        assert not _point_in_ring(1, 1, [(0, 0), (1, 1)])

    def test_empty_ring(self):
        assert not _point_in_ring(1, 1, [])

    def test_concave_ring(self):
        # L-shape
        ring = [(0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4)]
        assert _point_in_ring(1, 1, ring)
        assert not _point_in_ring(3, 3, ring)


class TestZoneContains:
    def test_circle_inside(self):
        z = Zone(name="p", center=(50.0, 25.0), radius_nm=10.0)
        assert z.contains(25.0, 50.0)

    def test_circle_outside(self):
        z = Zone(name="p", center=(50.0, 25.0), radius_nm=10.0)
        assert not z.contains(40.0, 60.0)

    def test_polygon_inside(self):
        z = Zone(name="p", polygon=SQUARE)
        assert z.contains(5.0, 5.0)

    def test_no_geometry_false(self):
        assert not Zone(name="empty").contains(0, 0)


class TestParseZones:
    def test_native_polygon(self):
        zs = parse_zones([{"name": "A", "kind": "eez", "polygon": SQUARE}])
        assert zs[0].name == "A" and zs[0].kind == "eez"

    def test_native_circle(self):
        zs = parse_zones([{"name": "P", "kind": "sanctioned_port",
                           "center": [50.0, 25.0], "radius_nm": 5}])
        assert zs[0].radius_nm == 5.0

    def test_zones_wrapper(self):
        zs = parse_zones({"zones": [{"name": "A", "polygon": SQUARE}]})
        assert len(zs) == 1

    def test_feature_collection(self):
        gj = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": "GJ", "kind": "exclusion"},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]]}}]}
        zs = parse_zones(gj)
        assert zs[0].name == "GJ" and zs[0].contains(1, 1)

    def test_single_feature(self):
        f = {"type": "Feature", "properties": {"name": "F"},
             "geometry": {"type": "Point", "coordinates": [50.0, 25.0]}}
        zs = parse_zones(f)
        assert zs[0].center == (50.0, 25.0)

    def test_bare_polygon_geometry(self):
        g = {"type": "Polygon", "name": "bare", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]]}
        zs = parse_zones(g)
        assert zs[0].contains(1, 1)

    def test_multipolygon_uses_first_ring(self):
        g = {"type": "MultiPolygon", "name": "mp",
             "coordinates": [[[[0, 0], [2, 0], [2, 2], [0, 2]]]]}
        zs = parse_zones(g)
        assert zs[0].contains(1, 1)

    def test_missing_center_only_raises(self):
        with pytest.raises(ValueError, match="both 'center' and 'radius_nm'"):
            parse_zones([{"name": "bad", "center": [1, 2]}])

    def test_radius_without_center_raises(self):
        with pytest.raises(ValueError, match="both 'center' and 'radius_nm'"):
            parse_zones([{"name": "bad", "radius_nm": 5}])

    def test_negative_radius_raises(self):
        with pytest.raises(ValueError, match="positive"):
            parse_zones([{"name": "bad", "center": [1, 2], "radius_nm": -3}])

    def test_no_geometry_raises(self):
        with pytest.raises(ValueError, match="no geometry"):
            parse_zones([{"name": "empty", "kind": "eez"}])

    def test_malformed_polygon_raises(self):
        with pytest.raises(ValueError, match="malformed polygon"):
            parse_zones([{"name": "bad", "polygon": [[1], [2], [3]]}])

    def test_scalar_input_rejected(self):
        with pytest.raises(ValueError):
            parse_zones(42)

    def test_unknown_dict_rejected(self):
        with pytest.raises(ValueError, match="GeoJSON or a list"):
            parse_zones({"foo": "bar"})


class TestLoadZones:
    def test_load_geojson_file(self, tmp_path):
        import json
        p = tmp_path / "z.geojson"
        p.write_text(json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": "Z"},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]]}}]}),
            encoding="utf-8")
        zs = Z.load_zones(str(p))
        assert zs[0].name == "Z"


class TestZonesForPoint:
    def test_multiple_zones(self):
        zs = parse_zones([
            {"name": "EEZ", "kind": "eez", "polygon": [[50, 25], [55, 25], [55, 30], [50, 30]]},
            {"name": "Port", "kind": "sanctioned_port", "center": [52, 27], "radius_nm": 10},
        ])
        assert zones_for_point(27.0, 52.0, zs) == ["EEZ", "Port"]

    def test_no_zone(self):
        zs = parse_zones([{"name": "Z", "polygon": SQUARE}])
        assert zones_for_point(50, 50, zs) == []


class TestZoneTransits:
    def _zones(self):
        return parse_zones([{"name": "Port", "kind": "sanctioned_port",
                             "center": [52.0, 27.0], "radius_nm": 10.0}])

    def test_single_visit(self):
        recs = [rec("A", 0, 27.0, 52.0), rec("A", 3, 27.05, 52.05), rec("A", 6, 10.0, 10.0)]
        f = detect_zone_transits(parse_messages(recs), self._zones())
        assert len(f) == 1 and f[0]["dwell_hours"] == pytest.approx(3.0, abs=0.1)

    def test_severity_by_kind(self):
        recs = [rec("A", 0, 27.0, 52.0), rec("A", 2, 27.0, 52.0)]
        assert detect_zone_transits(parse_messages(recs), self._zones())[0]["severity"] == "high"

    def test_eez_medium(self):
        z = parse_zones([{"name": "E", "kind": "eez", "center": [52, 27], "radius_nm": 10}])
        recs = [rec("A", 0, 27.0, 52.0), rec("A", 2, 27.0, 52.0)]
        assert detect_zone_transits(parse_messages(recs), z)[0]["severity"] == "medium"

    def test_two_visits_reported_separately(self):
        recs = [rec("A", 0, 27.0, 52.0), rec("A", 1, 27.0, 52.0),
                rec("A", 3, 10.0, 10.0),
                rec("A", 5, 27.0, 52.0), rec("A", 6, 27.0, 52.0)]
        assert len(detect_zone_transits(parse_messages(recs), self._zones())) == 2

    def test_no_transit(self):
        recs = [rec("A", 0, 10, 10), rec("A", 1, 11, 11)]
        assert detect_zone_transits(parse_messages(recs), self._zones()) == []

    def test_empty(self):
        assert detect_zone_transits([], self._zones()) == []


class TestAnnotateFindings:
    def _zones(self):
        return parse_zones([{"name": "Port", "kind": "sanctioned_port",
                             "center": [52.0, 27.0], "radius_nm": 10.0}])

    def test_tags_from_point(self):
        f = [{"type": "ais_gap", "from": [27.0, 52.0], "to": [10.0, 10.0]}]
        annotate_findings(f, self._zones())
        assert f[0]["zones"] == ["Port"]

    def test_no_tag_when_outside(self):
        f = [{"type": "ais_gap", "from": [0.0, 0.0]}]
        annotate_findings(f, self._zones())
        assert "zones" not in f[0]

    def test_dedup(self):
        f = [{"type": "loiter", "center": [27.0, 52.0], "from": [27.01, 52.01]}]
        annotate_findings(f, self._zones())
        assert f[0]["zones"] == ["Port"]

    def test_returns_list(self):
        f = []
        assert annotate_findings(f, self._zones()) is f
