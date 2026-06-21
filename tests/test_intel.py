"""Tests for the native intel-export module (GeoJSON / KML / STIX 2.1 / CSV)."""

import json

import pytest

from maritimeint import core, intel


def _analysis():
    msgs = core.load_messages("demos/ais_sample.json")
    return core.analyze(msgs)


def test_analysis_has_findings():
    a = _analysis()
    assert a["findings"], "demo should produce findings to export"


def test_geojson_is_valid_featurecollection():
    out = intel.to_geojson(_analysis())
    doc = json.loads(out)
    assert doc["type"] == "FeatureCollection"
    assert len(doc["features"]) == len(_analysis()["findings"])
    for feat in doc["features"]:
        assert feat["type"] == "Feature"
        assert "properties" in feat
        if feat["geometry"]:
            assert feat["geometry"]["type"] in ("Point", "LineString")


def test_geojson_uses_lon_lat_order():
    # the demo gap finding sits near lat 36.4, lon 22.9 -> coord must be [lon, lat]
    doc = json.loads(intel.to_geojson(_analysis()))
    pts = []
    for f in doc["features"]:
        g = f["geometry"]
        if g and g["type"] == "Point":
            pts.append(g["coordinates"])
        elif g and g["type"] == "LineString":
            pts.extend(g["coordinates"])
    assert any(20 < lon < 25 and 35 < lat < 38 for lon, lat in pts)


def test_stix_bundle_valid():
    doc = json.loads(intel.to_stix(_analysis()))
    assert doc["type"] == "bundle"
    assert doc["id"].startswith("bundle--")
    assert doc["objects"]
    for obj in doc["objects"]:
        assert obj["type"] == "indicator"
        assert obj["spec_version"] == "2.1"
        assert obj["id"].startswith("indicator--")
        assert obj["pattern_type"] == "stix"


def test_stix_ids_deterministic():
    a = _analysis()
    assert intel.to_stix(a) == intel.to_stix(a)


def test_kml_structure():
    out = intel.to_kml(_analysis())
    assert out.startswith("<?xml")
    assert "<kml" in out and "</kml>" in out
    assert out.count("<Placemark>") >= 1
    assert "<coordinates>" in out


def test_csv_has_header_and_rows():
    out = intel.to_csv(_analysis())
    lines = [l for l in out.splitlines() if l.strip()]
    assert lines[0].startswith("type,severity,mmsi")
    assert len(lines) >= 2


def test_export_dispatch_and_error():
    a = _analysis()
    assert json.loads(intel.export(a, "geojson"))["type"] == "FeatureCollection"
    assert intel.export(a, "kml").startswith("<?xml")
    with pytest.raises(ValueError):
        intel.export(a, "pdf")


def test_export_accepts_bare_findings_list():
    a = _analysis()
    doc = json.loads(intel.to_geojson(a["findings"]))
    assert doc["type"] == "FeatureCollection"
