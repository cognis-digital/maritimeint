"""Edge-case tests for maritimeint.intel exporters (GeoJSON / KML / STIX / CSV)."""
import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint import intel  # noqa: E402
from maritimeint.intel import (  # noqa: E402
    to_geojson,
    to_kml,
    to_stix,
    to_csv,
    export,
    _coords,
    _label,
    _timestamp,
    _findings,
    _xml_escape,
)


GAP = {"type": "ais_gap", "mmsi": "111", "name": "DARK", "severity": "high",
       "from": [26.0, 52.0], "to": [27.0, 53.0], "dark_from": "2026-01-04T00:00:00Z"}
POINT = {"type": "loitering", "mmsi": "222", "name": "LOIT", "severity": "medium",
         "center": [25.0, 55.0], "start": "2026-01-04T00:00:00Z"}
RDV = {"type": "rendezvous", "vessels": ["A", "B"], "severity": "high",
       "at": "2026-01-04T00:00:00Z", "from": [26.0, 52.0]}
NOGEO = {"type": "identity_conflict", "mmsi": "333", "names": ["X", "Y"], "severity": "high"}
RESULT = {"findings": [GAP, POINT, RDV, NOGEO]}


class TestFindingsExtraction:
    def test_from_result_dict(self):
        assert len(_findings(RESULT)) == 4

    def test_from_bare_list(self):
        assert len(_findings([GAP, POINT])) == 2

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _findings(42)


class TestCoords:
    def test_two_points_line(self):
        assert _coords(GAP) == [(26.0, 52.0), (27.0, 53.0)]

    def test_single_point(self):
        assert _coords(POINT) == [(25.0, 55.0)]

    def test_no_coords(self):
        assert _coords(NOGEO) == []

    def test_lat_lon_fields(self):
        assert _coords({"lat": 1.0, "lon": 2.0}) == [(1.0, 2.0)]

    def test_dedup(self):
        f = {"from": [1.0, 2.0], "center": [1.0, 2.0]}
        assert _coords(f) == [(1.0, 2.0)]

    def test_timestamp_string_not_treated_as_coords(self):
        # 'at' is in _POINT_KEYS but here it's a timestamp string -> ignored
        assert _coords({"at": "2026-01-04T00:00:00Z"}) == []


class TestLabel:
    def test_name_preferred(self):
        assert _label(GAP) == "ais_gap: DARK"

    def test_mmsi_fallback(self):
        assert _label({"type": "x", "mmsi": "9"}) == "x: 9"

    def test_vessels_fallback(self):
        assert _label({"type": "rendezvous", "vessels": ["A", "B"]}) == "rendezvous: A,B"

    def test_unknown(self):
        assert _label({}) == "finding: unknown"


class TestTimestamp:
    def test_timestamp_field(self):
        assert _timestamp({"timestamp": "2026-01-04T00:00:00Z"}) == "2026-01-04T00:00:00Z"

    def test_dark_from(self):
        assert _timestamp(GAP) == "2026-01-04T00:00:00Z"

    def test_appends_z(self):
        assert _timestamp({"start": "2026-01-04T00:00:00"}).endswith("Z")

    def test_fallback(self):
        assert _timestamp({}) == "2026-01-01T00:00:00.000Z"

    def test_invalid_string_falls_back(self):
        # a caller-supplied unparseable time must not leak into STIX valid_from
        assert _timestamp({"start": "yesterday"}) == "2026-01-01T00:00:00.000Z"

    def test_stix_valid_from_always_iso(self):
        b = json.loads(to_stix({"findings": [{"type": "x", "mmsi": "1", "start": "not-a-time"}]}))
        vf = b["objects"][0]["valid_from"]
        # must be parseable ISO-8601 (accepting Z suffix)
        from datetime import datetime
        datetime.fromisoformat(vf[:-1] + "+00:00" if vf.endswith("Z") else vf)


class TestGeoJSON:
    def test_valid_json(self):
        gj = json.loads(to_geojson(RESULT))
        assert gj["type"] == "FeatureCollection" and len(gj["features"]) == 4

    def test_line_for_two_points(self):
        gj = json.loads(to_geojson({"findings": [GAP]}))
        assert gj["features"][0]["geometry"]["type"] == "LineString"

    def test_point_for_one(self):
        gj = json.loads(to_geojson({"findings": [POINT]}))
        assert gj["features"][0]["geometry"]["type"] == "Point"

    def test_lon_lat_order(self):
        gj = json.loads(to_geojson({"findings": [POINT]}))
        # center is [lat=25, lon=55] -> GeoJSON coords [lon, lat] = [55, 25]
        assert gj["features"][0]["geometry"]["coordinates"] == [55.0, 25.0]

    def test_null_geometry_when_no_coords(self):
        gj = json.loads(to_geojson({"findings": [NOGEO]}))
        assert gj["features"][0]["geometry"] is None

    def test_label_in_props(self):
        gj = json.loads(to_geojson({"findings": [GAP]}))
        assert gj["features"][0]["properties"]["label"] == "ais_gap: DARK"

    def test_empty(self):
        gj = json.loads(to_geojson({"findings": []}))
        assert gj["features"] == []


class TestKML:
    def test_well_formed_xml(self):
        ET.fromstring(to_kml(RESULT))  # must parse

    def test_placemarks_for_geo_findings(self):
        root = ET.fromstring(to_kml(RESULT))
        pms = [e for e in root.iter() if e.tag.endswith("Placemark")]
        assert len(pms) == 3  # NOGEO has no coords -> skipped

    def test_linestring_present(self):
        assert "<LineString>" in to_kml({"findings": [GAP]})

    def test_point_present(self):
        assert "<Point>" in to_kml({"findings": [POINT]})

    def test_xml_escape_special_chars(self):
        f = {"type": "x", "name": "A & B <ship>", "center": [1, 2]}
        kml = to_kml({"findings": [f]})
        assert "&amp;" in kml and "&lt;" in kml
        ET.fromstring(kml)

    def test_empty_well_formed(self):
        ET.fromstring(to_kml({"findings": []}))


class TestXmlEscape:
    def test_all(self):
        assert _xml_escape('<a>&"') == "&lt;a&gt;&amp;&quot;"


class TestSTIX:
    def test_valid_bundle(self):
        b = json.loads(to_stix(RESULT))
        assert b["type"] == "bundle" and b["id"].startswith("bundle--")

    def test_indicator_objects(self):
        b = json.loads(to_stix(RESULT))
        assert all(o["type"] == "indicator" for o in b["objects"])
        assert len(b["objects"]) == 4

    def test_deterministic_ids(self):
        a = json.loads(to_stix({"findings": [GAP]}))["objects"][0]["id"]
        b = json.loads(to_stix({"findings": [GAP]}))["objects"][0]["id"]
        assert a == b

    def test_mmsi_pattern(self):
        b = json.loads(to_stix({"findings": [GAP]}))
        assert "111" in b["objects"][0]["pattern"]

    def test_vessels_pattern_uses_first(self):
        b = json.loads(to_stix({"findings": [RDV]}))
        assert "'A'" in b["objects"][0]["pattern"]

    def test_severity_label(self):
        b = json.loads(to_stix({"findings": [GAP]}))
        assert "high" in b["objects"][0]["labels"]

    def test_spec_version(self):
        b = json.loads(to_stix({"findings": [GAP]}))
        assert b["objects"][0]["spec_version"] == "2.1"

    def test_empty_bundle(self):
        b = json.loads(to_stix({"findings": []}))
        assert b["objects"] == []


class TestCSV:
    def test_header(self):
        assert to_csv(RESULT).splitlines()[0] == "type,severity,mmsi,name,lat,lon,detail"

    def test_row_count(self):
        assert len(to_csv(RESULT).strip().splitlines()) == 5  # header + 4

    def test_coords_filled(self):
        line = to_csv({"findings": [GAP]}).splitlines()[1]
        assert "26.0" in line and "52.0" in line

    def test_dict_field_ignored(self):
        # shadowing carries a 'names' dict; must not break DictWriter
        f = {"type": "shadowing", "vessels": ["A", "B"], "names": {"A": "x"},
             "severity": "high", "from": [1, 2]}
        out = to_csv({"findings": [f]})
        assert "shadowing" in out

    def test_detail_synthesized(self):
        line = to_csv({"findings": [NOGEO]}).splitlines()[1]
        assert "identity_conflict" in line

    def test_empty(self):
        assert to_csv({"findings": []}).strip() == "type,severity,mmsi,name,lat,lon,detail"


class TestExport:
    @pytest.mark.parametrize("fmt", ["geojson", "kml", "stix", "csv"])
    def test_dispatch(self, fmt):
        assert isinstance(export(RESULT, fmt), str)

    def test_case_insensitive(self):
        assert export(RESULT, "GEOJSON")

    def test_unknown_format(self):
        with pytest.raises(ValueError, match="unknown export format"):
            export(RESULT, "pdf")

    def test_accepts_analyze_result(self):
        from maritimeint.core import parse_messages, analyze
        m = parse_messages([{"mmsi": "A", "timestamp": "2026-01-04T00:00:00Z", "lat": 26, "lon": 52},
                            {"mmsi": "A", "timestamp": "2026-01-04T09:00:00Z", "lat": 27, "lon": 53}])
        assert json.loads(export(analyze(m), "geojson"))["type"] == "FeatureCollection"
