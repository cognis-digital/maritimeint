"""Edge-case & error-path tests for maritimeint.core.

Covers malformed AIS input, timestamp parsing, geodesy helpers, and the
per-detector boundaries (gaps / speed jumps / loitering / spoofing / rendezvous /
dark-rendezvous / GPS anomalies) plus the analyze() aggregator. Standard library
only, no network.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint import core  # noqa: E402
from maritimeint.core import (  # noqa: E402
    AISMessage,
    parse_messages,
    haversine_nm,
    detect_gaps,
    detect_speed_jumps,
    detect_loitering,
    detect_spoofing,
    detect_rendezvous,
    detect_dark_rendezvous,
    detect_gps_anomalies,
    analyze,
    _parse_ts,
    _bearing,
    _by_vessel,
)


def rec(mmsi, hour, lat, lon, **kw):
    r = {"mmsi": mmsi, "timestamp": f"2026-01-04T{hour:02d}:00:00Z",
         "lat": lat, "lon": lon}
    r.update(kw)
    return r


# --------------------------------------------------------------------------- #
# timestamp parsing
# --------------------------------------------------------------------------- #
class TestParseTs:
    def test_z_suffix(self):
        assert _parse_ts("2026-01-04T12:00:00Z").tzinfo is not None

    def test_offset_normalized_to_utc(self):
        dt = _parse_ts("2026-01-04T12:00:00+02:00")
        assert dt.hour == 10

    def test_naive_assumed_utc(self):
        dt = _parse_ts("2026-01-04T12:00:00")
        assert dt.utcoffset().total_seconds() == 0

    def test_space_separator(self):
        assert _parse_ts("2026-01-04 12:00:00").year == 2026

    def test_whitespace_trimmed(self):
        assert _parse_ts("  2026-01-04T12:00:00Z  ").minute == 0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("   ")

    def test_garbage_raises_clear(self):
        with pytest.raises(ValueError) as ei:
            _parse_ts("not-a-date")
        assert "not-a-date" in str(ei.value)

    def test_date_only(self):
        assert _parse_ts("2026-01-04").month == 1

    def test_fractional_seconds(self):
        assert _parse_ts("2026-01-04T12:00:00.500Z").microsecond == 500000


# --------------------------------------------------------------------------- #
# AISMessage.from_dict
# --------------------------------------------------------------------------- #
class TestFromDict:
    def test_minimal(self):
        m = AISMessage.from_dict(rec("1", 0, 1.0, 2.0))
        assert m.mmsi == "1" and m.lat == 1.0 and m.name == ""

    def test_mmsi_coerced_to_str(self):
        m = AISMessage.from_dict({"mmsi": 123456789, "timestamp": "2026-01-04T00:00:00Z",
                                  "lat": 1, "lon": 2})
        assert m.mmsi == "123456789"

    def test_missing_mmsi(self):
        with pytest.raises(ValueError, match="mmsi"):
            AISMessage.from_dict({"timestamp": "2026-01-04T00:00:00Z", "lat": 1, "lon": 2})

    @pytest.mark.parametrize("missing", ["timestamp", "lat", "lon"])
    def test_missing_required(self, missing):
        d = rec("1", 0, 1.0, 2.0)
        del d[missing]
        with pytest.raises(ValueError, match=missing):
            AISMessage.from_dict(d)

    def test_non_numeric_lat(self):
        with pytest.raises(ValueError, match="non-numeric lat"):
            AISMessage.from_dict({"mmsi": "1", "timestamp": "2026-01-04T00:00:00Z",
                                  "lat": "abc", "lon": 2})

    def test_non_numeric_lon(self):
        with pytest.raises(ValueError, match="non-numeric lon"):
            AISMessage.from_dict({"mmsi": "1", "timestamp": "2026-01-04T00:00:00Z",
                                  "lat": 1, "lon": "xyz"})

    def test_non_numeric_sog(self):
        with pytest.raises(ValueError, match="non-numeric sog"):
            AISMessage.from_dict(rec("1", 0, 1.0, 2.0, sog="fast"))

    def test_lat_out_of_range_high(self):
        with pytest.raises(ValueError, match="out-of-range lat"):
            AISMessage.from_dict(rec("1", 0, 91.0, 2.0))

    def test_lat_out_of_range_low(self):
        with pytest.raises(ValueError, match="out-of-range lat"):
            AISMessage.from_dict(rec("1", 0, -90.5, 2.0))

    def test_lon_out_of_range(self):
        with pytest.raises(ValueError, match="out-of-range lon"):
            AISMessage.from_dict(rec("1", 0, 1.0, 181.0))

    def test_lat_boundary_ok(self):
        assert AISMessage.from_dict(rec("1", 0, 90.0, 180.0)).lat == 90.0

    def test_non_dict_record(self):
        with pytest.raises(ValueError, match="object/dict"):
            AISMessage.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_sog_none_stays_none(self):
        assert AISMessage.from_dict(rec("1", 0, 1.0, 2.0, sog=None)).sog is None

    def test_sog_cog_parsed(self):
        m = AISMessage.from_dict(rec("1", 0, 1.0, 2.0, sog=12.5, cog=270))
        assert m.sog == 12.5 and m.cog == 270.0

    def test_as_record_roundtrip(self):
        m = AISMessage.from_dict(rec("1", 3, 1.0, 2.0, name="X"))
        r = m.as_record()
        assert r["timestamp"].endswith("Z") and r["mmsi"] == "1"

    def test_as_record_reparse(self):
        m = AISMessage.from_dict(rec("1", 3, 1.5, 2.5, name="X", sog=5, cog=90))
        m2 = AISMessage.from_dict(m.as_record())
        assert m2.lat == m.lat and m2.timestamp == m.timestamp


# --------------------------------------------------------------------------- #
# parse_messages
# --------------------------------------------------------------------------- #
class TestParseMessages:
    def test_empty(self):
        assert parse_messages([]) == []

    def test_sorted_by_mmsi_then_time(self):
        msgs = parse_messages([rec("B", 2, 1, 1), rec("A", 5, 1, 1), rec("A", 1, 1, 1)])
        assert [m.mmsi for m in msgs] == ["A", "A", "B"]
        assert msgs[0].timestamp < msgs[1].timestamp

    def test_one_bad_record_raises(self):
        with pytest.raises(ValueError):
            parse_messages([rec("A", 0, 1, 1), {"mmsi": "B"}])


# --------------------------------------------------------------------------- #
# load_messages
# --------------------------------------------------------------------------- #
class TestLoadMessages:
    def test_json_list(self, tmp_path):
        import json
        p = tmp_path / "a.json"
        p.write_text(json.dumps([rec("1", 0, 1, 2)]), encoding="utf-8")
        assert len(core.load_messages(str(p))) == 1

    def test_json_messages_wrapper(self, tmp_path):
        import json
        p = tmp_path / "a.json"
        p.write_text(json.dumps({"messages": [rec("1", 0, 1, 2)]}), encoding="utf-8")
        assert len(core.load_messages(str(p))) == 1

    def test_json_records_wrapper(self, tmp_path):
        import json
        p = tmp_path / "a.json"
        p.write_text(json.dumps({"records": [rec("1", 0, 1, 2)]}), encoding="utf-8")
        assert len(core.load_messages(str(p))) == 1

    def test_csv(self, tmp_path):
        p = tmp_path / "a.csv"
        p.write_text("mmsi,timestamp,lat,lon,name\n1,2026-01-04T00:00:00Z,1.0,2.0,X\n",
                     encoding="utf-8")
        msgs = core.load_messages(str(p))
        assert msgs[0].name == "X"

    def test_csv_empty_cells_optional(self, tmp_path):
        p = tmp_path / "a.csv"
        p.write_text("mmsi,timestamp,lat,lon,sog\n1,2026-01-04T00:00:00Z,1.0,2.0,\n",
                     encoding="utf-8")
        assert core.load_messages(str(p))[0].sog is None

    def test_bad_json_clear_error(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            core.load_messages(str(p))

    def test_json_scalar_rejected(self, tmp_path):
        import json
        p = tmp_path / "a.json"
        p.write_text(json.dumps(42), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON list"):
            core.load_messages(str(p))

    def test_missing_file(self, tmp_path):
        with pytest.raises(OSError):
            core.load_messages(str(tmp_path / "nope.json"))


# --------------------------------------------------------------------------- #
# haversine / bearing
# --------------------------------------------------------------------------- #
class TestGeodesy:
    def test_same_point_zero(self):
        assert haversine_nm(10, 20, 10, 20) == 0.0

    def test_one_degree_lat_is_60nm(self):
        assert haversine_nm(0, 0, 1, 0) == pytest.approx(60.0, abs=0.5)

    def test_symmetry(self):
        a = haversine_nm(10, 20, 30, 40)
        b = haversine_nm(30, 40, 10, 20)
        assert a == pytest.approx(b)

    def test_antipodal_bounded(self):
        d = haversine_nm(0, 0, 0, 180)
        assert 10000 < d < 11000

    def test_bearing_north(self):
        assert _bearing(0, 0, 1, 0) == pytest.approx(0.0, abs=1.0)

    def test_bearing_east(self):
        assert _bearing(0, 0, 0, 1) == pytest.approx(90.0, abs=1.0)

    def test_bearing_range(self):
        for lat, lon in [(1, 1), (-1, -1), (1, -1), (-1, 1)]:
            b = _bearing(0, 0, lat, lon)
            assert 0.0 <= b < 360.0


# --------------------------------------------------------------------------- #
# _by_vessel
# --------------------------------------------------------------------------- #
class TestByVessel:
    def test_groups_and_sorts(self):
        msgs = parse_messages([rec("A", 5, 1, 1), rec("B", 0, 1, 1), rec("A", 1, 1, 1)])
        tracks = _by_vessel(msgs)
        assert set(tracks) == {"A", "B"}
        assert tracks["A"][0].timestamp < tracks["A"][1].timestamp

    def test_empty(self):
        assert _by_vessel([]) == {}


# --------------------------------------------------------------------------- #
# detect_gaps
# --------------------------------------------------------------------------- #
class TestGaps:
    def test_no_gap_below_threshold(self):
        m = parse_messages([rec("A", 0, 1, 1), rec("A", 3, 1, 1)])
        assert detect_gaps(m, gap_hours=6.0) == []

    def test_gap_at_threshold(self):
        m = parse_messages([rec("A", 0, 1, 1), rec("A", 6, 1, 1)])
        assert len(detect_gaps(m, gap_hours=6.0)) == 1

    def test_severity_medium_vs_high(self):
        m = parse_messages([rec("A", 0, 1, 1), rec("A", 7, 1, 1)])
        assert detect_gaps(m, gap_hours=6.0)[0]["severity"] == "medium"
        m2 = parse_messages([rec("A", 0, 1, 1), rec("A", 13, 1, 1)])
        assert detect_gaps(m2, gap_hours=6.0)[0]["severity"] == "high"

    def test_single_report_no_gap(self):
        assert detect_gaps(parse_messages([rec("A", 0, 1, 1)])) == []

    def test_empty(self):
        assert detect_gaps([]) == []

    def test_multiple_vessels(self):
        m = parse_messages([rec("A", 0, 1, 1), rec("A", 8, 1, 1),
                            rec("B", 0, 2, 2), rec("B", 9, 2, 2)])
        assert len(detect_gaps(m)) == 2

    def test_distance_recorded(self):
        m = parse_messages([rec("A", 0, 26.0, 52.0), rec("A", 8, 26.5, 52.5)])
        f = detect_gaps(m)[0]
        assert f["distance_nm"] > 0 and "dark_from" in f and "dark_to" in f


# --------------------------------------------------------------------------- #
# detect_speed_jumps
# --------------------------------------------------------------------------- #
class TestSpeedJumps:
    def test_teleport_flagged(self):
        m = parse_messages([rec("A", 0, 0, 0), rec("A", 1, 5, 0)])  # 300nm/h
        f = detect_speed_jumps(m, max_speed_kn=40.0)
        assert len(f) == 1 and f[0]["implied_speed_kn"] > 40

    def test_slow_not_flagged(self):
        m = parse_messages([rec("A", 0, 0, 0), rec("A", 10, 1, 0)])  # 6nm/h
        assert detect_speed_jumps(m) == []

    def test_zero_dt_skipped(self):
        m = parse_messages([{"mmsi": "A", "timestamp": "2026-01-04T00:00:00Z", "lat": 0, "lon": 0},
                            {"mmsi": "A", "timestamp": "2026-01-04T00:00:00Z", "lat": 5, "lon": 0}])
        assert detect_speed_jumps(m) == []

    def test_custom_threshold(self):
        m = parse_messages([rec("A", 0, 0, 0), rec("A", 1, 0.9, 0)])  # ~54nm/h
        assert detect_speed_jumps(m, max_speed_kn=100.0) == []
        assert len(detect_speed_jumps(m, max_speed_kn=40.0)) == 1

    def test_severity_high(self):
        m = parse_messages([rec("A", 0, 0, 0), rec("A", 1, 5, 0)])
        assert detect_speed_jumps(m)[0]["severity"] == "high"


# --------------------------------------------------------------------------- #
# detect_loitering
# --------------------------------------------------------------------------- #
class TestLoitering:
    def test_stationary_loiter(self):
        m = parse_messages([rec("A", h, 25.0, 55.0) for h in range(6)])
        f = detect_loitering(m, radius_nm=2.0, min_hours=4.0)
        assert len(f) == 1 and f[0]["duration_hours"] >= 4.0

    def test_moving_not_loiter(self):
        m = parse_messages([rec("A", h, 25.0 + h, 55.0) for h in range(6)])
        assert detect_loitering(m) == []

    def test_short_dwell_not_loiter(self):
        m = parse_messages([rec("A", 0, 25, 55), rec("A", 2, 25, 55)])
        assert detect_loitering(m, min_hours=4.0) == []

    def test_center_computed(self):
        m = parse_messages([rec("A", h, 25.0, 55.0) for h in range(6)])
        c = detect_loitering(m)[0]["center"]
        assert c[0] == pytest.approx(25.0, abs=0.01)

    def test_empty(self):
        assert detect_loitering([]) == []


# --------------------------------------------------------------------------- #
# detect_spoofing
# --------------------------------------------------------------------------- #
class TestSpoofing:
    def test_identity_conflict(self):
        m = parse_messages([rec("A", 0, 1, 1, name="ALPHA"), rec("A", 1, 1, 1, name="BETA")])
        f = [x for x in detect_spoofing(m) if x["type"] == "identity_conflict"]
        assert len(f) == 1 and set(f[0]["names"]) == {"ALPHA", "BETA"}

    def test_single_name_no_conflict(self):
        m = parse_messages([rec("A", 0, 1, 1, name="ALPHA"), rec("A", 1, 1, 1, name="ALPHA")])
        assert [x for x in detect_spoofing(m) if x["type"] == "identity_conflict"] == []

    def test_static_pin(self):
        m = parse_messages([rec("A", h, 25.12345, 55.12345, name="P") for h in range(4)])
        f = [x for x in detect_spoofing(m) if x["type"] == "static_pin"]
        assert len(f) == 1 and f[0]["reports"] >= 3

    def test_static_pin_needs_span(self):
        # 3 reports same minute -> span < 1h -> no pin
        m = parse_messages([{"mmsi": "A", "timestamp": f"2026-01-04T00:0{i}:00Z",
                             "lat": 25.1, "lon": 55.1, "name": "P"} for i in range(3)])
        assert [x for x in detect_spoofing(m) if x["type"] == "static_pin"] == []

    def test_empty(self):
        assert detect_spoofing([]) == []


# --------------------------------------------------------------------------- #
# detect_rendezvous
# --------------------------------------------------------------------------- #
class TestRendezvous:
    def _pair(self):
        recs = []
        for h in range(3):
            recs.append(rec("A", h, 25.0, 55.0, name="TANKER"))
            recs.append(rec("B", h, 25.001, 55.001, name="LIGHTER"))
        return parse_messages(recs)

    def test_meeting_found(self):
        f = detect_rendezvous(self._pair(), proximity_nm=0.5, min_minutes=30.0)
        assert len(f) == 1 and set(f[0]["vessels"]) == {"A", "B"}

    def test_far_apart_no_meeting(self):
        recs = []
        for h in range(3):
            recs.append(rec("A", h, 25.0, 55.0))
            recs.append(rec("B", h, 30.0, 60.0))
        assert detect_rendezvous(parse_messages(recs)) == []

    def test_single_vessel_no_pair(self):
        m = parse_messages([rec("A", h, 25, 55) for h in range(3)])
        assert detect_rendezvous(m) == []

    def test_severity_high(self):
        assert detect_rendezvous(self._pair())[0]["severity"] == "high"


# --------------------------------------------------------------------------- #
# detect_dark_rendezvous
# --------------------------------------------------------------------------- #
class TestDarkRendezvous:
    def _scene(self):
        recs = [
            rec("A", 0, 26.0, 52.0, name="DARK"),
            rec("A", 8, 26.1, 52.1, name="DARK"),
            {"mmsi": "B", "timestamp": "2026-01-04T03:00:00Z", "lat": 26.02, "lon": 52.02, "name": "L"},
            {"mmsi": "B", "timestamp": "2026-01-04T04:00:00Z", "lat": 26.01, "lon": 52.01, "name": "L"},
        ]
        return parse_messages(recs)

    def test_found(self):
        f = detect_dark_rendezvous(self._scene())
        assert len(f) == 1 and f[0]["dark_vessel"] == "A"

    def test_present_reports_counted(self):
        assert detect_dark_rendezvous(self._scene())[0]["present_reports"] == 2

    def test_far_vessel_excluded(self):
        recs = [rec("A", 0, 26.0, 52.0), rec("A", 8, 26.1, 52.1),
                rec("B", 3, 10.0, 10.0)]
        assert detect_dark_rendezvous(parse_messages(recs)) == []

    def test_no_gap_no_rendezvous(self):
        recs = [rec("A", 0, 26.0, 52.0), rec("A", 1, 26.0, 52.0),
                rec("B", 0, 26.0, 52.0)]
        assert detect_dark_rendezvous(recs and parse_messages(recs)) == []


# --------------------------------------------------------------------------- #
# detect_gps_anomalies
# --------------------------------------------------------------------------- #
def _circle(mmsi, clat, clon, radius_nm=0.5, n=9):
    deg = radius_nm / 60.0
    out = []
    for k in range(n):
        ang = math.radians(k * (360.0 / (n - 1)))
        lat = clat + deg * math.cos(ang)
        lon = clon + deg * math.sin(ang) / math.cos(math.radians(clat))
        out.append({"mmsi": mmsi, "timestamp": f"2026-01-04T{k:02d}:00:00Z",
                    "lat": round(lat, 6), "lon": round(lon, 6), "name": "C"})
    return out


class TestGpsAnomalies:
    def test_circle_spoof(self):
        f = detect_gps_anomalies(parse_messages(_circle("S", 25, 55)))
        circ = [x for x in f if x["type"] == "circle_spoof"]
        assert len(circ) == 1 and circ[0]["arc_degrees"] >= 300

    def test_straight_line_no_circle(self):
        m = parse_messages([rec("L", h, 20.0 + 0.05 * h, 40.0) for h in range(10)])
        assert [x for x in detect_gps_anomalies(m) if x["type"] == "circle_spoof"] == []

    def test_too_few_points_no_circle(self):
        m = parse_messages(_circle("S", 25, 55, n=4))
        assert [x for x in detect_gps_anomalies(m) if x["type"] == "circle_spoof"] == []

    def test_jamming_hotspot(self):
        recs = [{"mmsi": f"J{i}", "timestamp": f"2026-01-04T12:0{i}:00Z",
                 "lat": 40.1234, "lon": 50.1234, "name": f"V{i}"} for i in range(4)]
        jam = [x for x in detect_gps_anomalies(parse_messages(recs)) if x["type"] == "gps_jamming"]
        assert len(jam) == 1 and jam[0]["vessel_count"] == 4

    def test_two_vessels_below_jam_threshold(self):
        recs = [{"mmsi": f"J{i}", "timestamp": f"2026-01-04T12:0{i}:00Z",
                 "lat": 40.1, "lon": 50.1} for i in range(2)]
        assert [x for x in detect_gps_anomalies(parse_messages(recs)) if x["type"] == "gps_jamming"] == []

    def test_empty(self):
        assert detect_gps_anomalies([]) == []


# --------------------------------------------------------------------------- #
# analyze
# --------------------------------------------------------------------------- #
class TestAnalyze:
    def test_empty_report_shape(self):
        r = analyze([])
        assert r["tool"] == "maritimeint"
        assert r["vessels_tracked"] == 0
        assert r["messages"] == 0
        assert r["findings"] == []
        assert set(r["finding_counts"]) >= {"ais_gap", "speed_jump", "loitering",
                                            "rendezvous", "convoy", "drift"}

    def test_counts_match_findings(self):
        m = parse_messages([rec("A", 0, 26.0, 52.0, name="X"),
                            rec("A", 9, 26.1, 52.1, name="X")])
        r = analyze(m)
        assert r["finding_counts"]["ais_gap"] == 1

    def test_risk_ranking_sorted(self):
        m = parse_messages([rec("A", 0, 26.0, 52.0, name="X"),
                            rec("A", 12, 26.5, 52.5, name="X")])
        r = analyze(m)
        scores = [row["risk_score"] for row in r["risk_ranking"]]
        assert scores == sorted(scores, reverse=True)

    def test_kwargs_thread_through(self):
        m = parse_messages([rec("A", 0, 26.0, 52.0), rec("A", 5, 26.0, 52.0)])
        assert analyze(m, gap_hours=4.0)["finding_counts"]["ais_gap"] == 1
        assert analyze(m, gap_hours=8.0)["finding_counts"]["ais_gap"] == 0

    def test_serializable(self):
        import json
        m = parse_messages([rec("A", 0, 26.0, 52.0), rec("A", 9, 26.5, 52.5)])
        json.dumps(analyze(m))  # must not raise

    def test_finding_counts_all_zero_on_empty(self):
        counts = analyze([])["finding_counts"]
        assert all(v == 0 for v in counts.values())

    def test_single_vessel_single_report(self):
        r = analyze(parse_messages([rec("A", 0, 1, 1)]))
        assert r["vessels_tracked"] == 1 and r["messages"] == 1

    def test_risk_ranking_only_flagged_vessels(self):
        # a clean vessel with two nearby reports should not dominate the ranking
        m = parse_messages([rec("A", 0, 26, 52), rec("A", 12, 27, 53),
                            rec("CLEAN", 0, 10, 10), rec("CLEAN", 1, 10.001, 10.001)])
        r = analyze(m)
        top = r["risk_ranking"][0]["mmsi"]
        assert top == "A"


class TestSpoofingMore:
    def test_three_distinct_names(self):
        m = parse_messages([rec("A", 0, 1, 1, name="X"), rec("A", 1, 1, 1, name="Y"),
                            rec("A", 2, 1, 1, name="Z")])
        f = [x for x in detect_spoofing(m) if x["type"] == "identity_conflict"]
        assert len(f) == 1 and len(f[0]["names"]) == 3

    def test_blank_names_ignored(self):
        m = parse_messages([rec("A", 0, 1, 1, name=""), rec("A", 1, 1, 1, name="ONLY")])
        assert [x for x in detect_spoofing(m) if x["type"] == "identity_conflict"] == []

    def test_static_pin_severity_medium(self):
        m = parse_messages([rec("A", h, 25.1, 55.1, name="P") for h in range(4)])
        pins = [x for x in detect_spoofing(m) if x["type"] == "static_pin"]
        assert pins and pins[0]["severity"] == "medium"


class TestSpeedJumpsMore:
    def test_multiple_jumps_one_vessel(self):
        m = parse_messages([rec("A", 0, 0, 0), rec("A", 1, 5, 0), rec("A", 2, 0, 0)])
        assert len(detect_speed_jumps(m)) == 2

    def test_records_positions(self):
        m = parse_messages([rec("A", 0, 0, 0), rec("A", 1, 5, 0)])
        f = detect_speed_jumps(m)[0]
        assert f["from"] == [0.0, 0.0] and f["to"][0] == 5.0


class TestGapsMore:
    def test_exact_double_threshold_high(self):
        m = parse_messages([rec("A", 0, 1, 1), rec("A", 12, 1, 1)])
        assert detect_gaps(m, gap_hours=6.0)[0]["severity"] == "high"

    def test_from_to_recorded(self):
        m = parse_messages([rec("A", 0, 26.0, 52.0), rec("A", 8, 27.0, 53.0)])
        f = detect_gaps(m)[0]
        assert f["from"] == [26.0, 52.0] and f["to"] == [27.0, 53.0]
