"""Edge-case tests for maritimeint.ais_fetch — malformed / partial provider records."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint import ais_fetch as AF  # noqa: E402
from maritimeint.ais_fetch import normalize_records, from_file, _iso, write_ais  # noqa: E402


class TestIso:
    def test_unix_seconds(self):
        assert _iso(1704326400).endswith("Z")

    def test_unix_string(self):
        assert _iso("1704326400").endswith("Z")

    def test_iso_passthrough(self):
        assert _iso("2026-01-04T00:00:00Z") in ("2026-01-04T00:00:00Z",)

    def test_empty(self):
        assert _iso("") == ""

    def test_none(self):
        assert _iso(None) == ""

    def test_non_numeric_string_kept(self):
        assert _iso("2026-01-04 sometime") == "2026-01-04 sometime"


class TestNormalizeRecords:
    def test_field_aliases(self):
        rows = [{"MMSI": "123", "latitude": "26.0", "longitude": "52.0",
                 "BaseDateTime": "2026-01-04T00:00:00Z", "shipname": "X"}]
        out = normalize_records(rows)
        assert out[0]["mmsi"] == "123" and out[0]["lat"] == 26.0 and out[0]["name"] == "X"

    def test_lng_alias(self):
        rows = [{"mmsi": "1", "lat": "1", "lng": "2", "t": "2026-01-04T00:00:00Z"}]
        assert normalize_records(rows)[0]["lon"] == 2.0

    def test_speed_course_aliases(self):
        rows = [{"mmsi": "1", "lat": "1", "lon": "2", "time": "2026-01-04T00:00:00Z",
                 "speed": "12", "course": "270"}]
        out = normalize_records(rows)
        assert out[0]["sog"] == 12.0 and out[0]["cog"] == 270.0

    def test_missing_mmsi_dropped(self):
        assert normalize_records([{"lat": "1", "lon": "2", "time": "2026-01-04T00:00:00Z"}]) == []

    def test_missing_lat_dropped(self):
        assert normalize_records([{"mmsi": "1", "lon": "2", "time": "2026-01-04T00:00:00Z"}]) == []

    def test_non_numeric_lat_dropped(self):
        assert normalize_records([{"mmsi": "1", "lat": "abc", "lon": "2",
                                   "time": "2026-01-04T00:00:00Z"}]) == []

    def test_missing_timestamp_dropped(self):
        assert normalize_records([{"mmsi": "1", "lat": "1", "lon": "2"}]) == []

    def test_bad_sog_dropped_but_record_kept(self):
        rows = [{"mmsi": "1", "lat": "1", "lon": "2", "time": "2026-01-04T00:00:00Z",
                 "speed": "notaspeed"}]
        out = normalize_records(rows)
        assert len(out) == 1 and "sog" not in out[0]

    def test_mmsi_stripped(self):
        rows = [{"mmsi": "  123  ", "lat": "1", "lon": "2", "time": "2026-01-04T00:00:00Z"}]
        assert normalize_records(rows)[0]["mmsi"] == "123"

    def test_mixed_valid_invalid(self):
        rows = [
            {"mmsi": "1", "lat": "1", "lon": "2", "time": "2026-01-04T00:00:00Z"},
            {"mmsi": "2"},  # dropped
            {"mmsi": "3", "lat": "3", "lon": "4", "time": "2026-01-04T01:00:00Z"},
        ]
        assert len(normalize_records(rows)) == 2

    def test_empty(self):
        assert normalize_records([]) == []

    def test_output_parses_through_core(self):
        from maritimeint.core import parse_messages
        rows = [{"mmsi": "1", "lat": "26.0", "lon": "52.0", "time": "2026-01-04T00:00:00Z"}]
        parse_messages(normalize_records(rows))  # must not raise


class TestFromFile:
    def test_csv(self, tmp_path):
        p = tmp_path / "p.csv"
        p.write_text("mmsi,latitude,longitude,time\n1,26.0,52.0,2026-01-04T00:00:00Z\n",
                     encoding="utf-8")
        assert from_file(str(p))[0]["mmsi"] == "1"

    def test_json_list(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text(json.dumps([{"mmsi": "1", "lat": 26.0, "lon": 52.0,
                                  "time": "2026-01-04T00:00:00Z"}]), encoding="utf-8")
        assert len(from_file(str(p))) == 1

    def test_json_data_wrapper(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text(json.dumps({"data": [{"mmsi": "1", "lat": 26.0, "lon": 52.0,
                                           "time": "2026-01-04T00:00:00Z"}]}), encoding="utf-8")
        assert len(from_file(str(p))) == 1

    def test_aishub_nested_shape(self, tmp_path):
        # AISHub JSON is [[meta], [vessels]]
        p = tmp_path / "p.json"
        payload = [[{"ERROR": False}], [{"MMSI": "1", "LATITUDE": 26.0, "LONGITUDE": 52.0,
                                         "TIME": "2026-01-04T00:00:00Z"}]]
        p.write_text(json.dumps(payload), encoding="utf-8")
        assert len(from_file(str(p))) == 1


class TestWriteAis:
    def test_roundtrip(self, tmp_path):
        recs = [{"mmsi": "1", "lat": 26.0, "lon": 52.0, "timestamp": "2026-01-04T00:00:00Z"}]
        p = tmp_path / "out.json"
        write_ais(recs, str(p))
        assert json.loads(p.read_text(encoding="utf-8")) == recs


def test_aisstream_note_exists():
    assert isinstance(AF.AISSTREAM_NOTE, str) and "aisstream" in AF.AISSTREAM_NOTE
