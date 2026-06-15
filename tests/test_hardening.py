"""Hardening tests: bad input, edge cases, and error paths. No network."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import (  # noqa: E402
    AISMessage,
    parse_messages,
    load_messages,
    detect_gaps,
    detect_speed_jumps,
    detect_loitering,
    detect_spoofing,
    detect_rendezvous,
    analyze,
)
from maritimeint.cli import main  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record(**kw):
    base = {
        "mmsi": "123456789",
        "timestamp": "2026-01-01T00:00:00Z",
        "lat": 10.0,
        "lon": 50.0,
    }
    base.update(kw)
    return base


def _write_json(obj, suffix=".json"):
    """Write obj as JSON to a temp file, return the path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


# ---------------------------------------------------------------------------
# AISMessage.from_dict — missing/bad fields
# ---------------------------------------------------------------------------

class TestAISMessageValidation(unittest.TestCase):
    def test_missing_mmsi_raises(self):
        with self.assertRaises(ValueError) as ctx:
            AISMessage.from_dict({"timestamp": "2026-01-01T00:00:00Z",
                                  "lat": 0, "lon": 0})
        self.assertIn("mmsi", str(ctx.exception))

    def test_missing_lat_raises(self):
        with self.assertRaises(ValueError) as ctx:
            AISMessage.from_dict({"mmsi": "123", "timestamp": "2026-01-01T00:00:00Z",
                                  "lon": 0})
        self.assertIn("lat", str(ctx.exception))

    def test_missing_lon_raises(self):
        with self.assertRaises(ValueError) as ctx:
            AISMessage.from_dict({"mmsi": "123", "timestamp": "2026-01-01T00:00:00Z",
                                  "lat": 0})
        self.assertIn("lon", str(ctx.exception))

    def test_lat_out_of_range_raises(self):
        with self.assertRaises(ValueError) as ctx:
            AISMessage.from_dict(_record(lat=91.0))
        self.assertIn("lat", str(ctx.exception).lower())

    def test_lon_out_of_range_raises(self):
        with self.assertRaises(ValueError) as ctx:
            AISMessage.from_dict(_record(lon=181.0))
        self.assertIn("lon", str(ctx.exception).lower())

    def test_lat_negative_edge_valid(self):
        # -90 and +90 are valid poles
        msg = AISMessage.from_dict(_record(lat=-90.0, lon=0.0))
        self.assertEqual(msg.lat, -90.0)

    def test_non_dict_record_raises(self):
        with self.assertRaises(ValueError):
            AISMessage.from_dict("not a dict")  # type: ignore[arg-type]

    def test_bad_timestamp_raises(self):
        with self.assertRaises(ValueError) as ctx:
            AISMessage.from_dict(_record(timestamp="not-a-date"))
        self.assertIn("timestamp", str(ctx.exception).lower())

    def test_empty_timestamp_raises(self):
        with self.assertRaises(ValueError):
            AISMessage.from_dict(_record(timestamp="   "))

    def test_non_numeric_lat_raises(self):
        with self.assertRaises(ValueError):
            AISMessage.from_dict(_record(lat="NaN-string"))


# ---------------------------------------------------------------------------
# parse_messages — empty and bad input
# ---------------------------------------------------------------------------

class TestParseMessages(unittest.TestCase):
    def test_empty_list_returns_empty(self):
        result = parse_messages([])
        self.assertEqual(result, [])

    def test_bad_record_includes_index(self):
        records = [
            _record(mmsi="AAA"),
            {"mmsi": "BBB"},          # missing timestamp, lat, lon
        ]
        with self.assertRaises(ValueError) as ctx:
            parse_messages(records)
        self.assertIn("record[1]", str(ctx.exception))


# ---------------------------------------------------------------------------
# load_messages — file errors
# ---------------------------------------------------------------------------

class TestLoadMessages(unittest.TestCase):
    def test_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            load_messages("/no/such/file.json")

    def test_malformed_json_raises(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as fh:
            fh.write("{ not valid json }")
        try:
            with self.assertRaises(json.JSONDecodeError):
                load_messages(path)
        finally:
            os.unlink(path)

    def test_wrong_top_level_type_raises(self):
        path = _write_json({"messages": "not-a-list"})
        try:
            with self.assertRaises(ValueError) as ctx:
                load_messages(path)
            self.assertIn("JSON list", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_plain_number_top_level_raises(self):
        path = _write_json(42)
        try:
            with self.assertRaises(ValueError):
                load_messages(path)
        finally:
            os.unlink(path)

    def test_messages_key_parsed(self):
        path = _write_json({"messages": [_record()]})
        try:
            msgs = load_messages(path)
            self.assertEqual(len(msgs), 1)
        finally:
            os.unlink(path)

    def test_records_key_parsed(self):
        path = _write_json({"records": [_record()]})
        try:
            msgs = load_messages(path)
            self.assertEqual(len(msgs), 1)
        finally:
            os.unlink(path)

    def test_empty_list_file(self):
        path = _write_json([])
        try:
            msgs = load_messages(path)
            self.assertEqual(msgs, [])
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Detectors with empty input
# ---------------------------------------------------------------------------

class TestDetectorsEmptyInput(unittest.TestCase):
    def test_gaps_empty(self):
        self.assertEqual(detect_gaps([]), [])

    def test_speed_jumps_empty(self):
        self.assertEqual(detect_speed_jumps([]), [])

    def test_loitering_empty(self):
        self.assertEqual(detect_loitering([]), [])

    def test_spoofing_empty(self):
        self.assertEqual(detect_spoofing([]), [])

    def test_rendezvous_empty(self):
        self.assertEqual(detect_rendezvous([]), [])

    def test_analyze_empty(self):
        rep = analyze([])
        self.assertEqual(rep["vessels_tracked"], 0)
        self.assertEqual(rep["messages"], 0)
        self.assertEqual(rep["risk_ranking"], [])

    def test_single_message_no_findings(self):
        msgs = parse_messages([_record()])
        self.assertEqual(detect_gaps(msgs), [])
        self.assertEqual(detect_speed_jumps(msgs), [])
        self.assertEqual(detect_loitering(msgs), [])


# ---------------------------------------------------------------------------
# CLI — bad arguments produce non-zero exit
# ---------------------------------------------------------------------------

class TestCLIHardening(unittest.TestCase):
    def setUp(self):
        self._path = _write_json([_record()])

    def tearDown(self):
        os.unlink(self._path)

    def test_missing_file_returns_1(self):
        rc = main(["analyze", "/no/such/feed.json"])
        self.assertEqual(rc, 1)

    def test_malformed_json_returns_1(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as fh:
            fh.write("!!!bad!!!")
        try:
            rc = main(["analyze", path])
            self.assertEqual(rc, 1)
        finally:
            os.unlink(path)

    def test_gaps_zero_hours_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["gaps", "--gap-hours", "0", self._path])
        self.assertEqual(ctx.exception.code, 2)

    def test_jumps_negative_speed_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["jumps", "--max-speed-kn", "-5", self._path])
        self.assertEqual(ctx.exception.code, 2)

    def test_loiter_zero_radius_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["loiter", "--radius-nm", "0", self._path])
        self.assertEqual(ctx.exception.code, 2)

    def test_rendezvous_zero_proximity_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["rendezvous", "--proximity-nm", "0", self._path])
        self.assertEqual(ctx.exception.code, 2)

    def test_valid_single_record_analyze(self):
        rc = main(["analyze", self._path])
        self.assertEqual(rc, 0)

    def test_lat_out_of_range_returns_1(self):
        path = _write_json([_record(lat=200.0)])
        try:
            rc = main(["analyze", path])
            self.assertEqual(rc, 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
