"""Edge-case tests for maritimeint.ports (port-call inference + itineraries)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import parse_messages  # noqa: E402
from maritimeint import ports as P  # noqa: E402
from maritimeint.ports import (  # noqa: E402
    builtin_ports,
    load_ports,
    detect_port_calls,
    sequence_itineraries,
    _nearest_port,
)


class TestBuiltinPorts:
    def test_nonempty(self):
        assert len(builtin_ports()) >= 10

    def test_has_sanctioned(self):
        assert any(p["risk"] == "sanctioned" for p in builtin_ports())

    def test_shape(self):
        p = builtin_ports()[0]
        assert {"name", "country", "lat", "lon", "radius_nm", "risk"} <= set(p)


class TestNearestPort:
    def test_inside_radius(self):
        p = _nearest_port(29.23, 50.32, builtin_ports())
        assert p and p["name"] == "Kharg Island"

    def test_open_water_none(self):
        assert _nearest_port(0.0, 0.0, builtin_ports()) is None

    def test_picks_closest_when_overlapping(self):
        ports = [{"name": "Near", "country": "X", "lat": 1.0, "lon": 1.0, "radius_nm": 100, "risk": "normal"},
                 {"name": "Far", "country": "X", "lat": 1.5, "lon": 1.5, "radius_nm": 100, "risk": "normal"}]
        assert _nearest_port(1.0, 1.0, ports)["name"] == "Near"


class TestLoadPorts:
    def test_list(self, tmp_path):
        p = tmp_path / "ports.json"
        p.write_text(json.dumps([{"name": "C", "lat": 5, "lon": 5}]), encoding="utf-8")
        assert load_ports(str(p))[0]["name"] == "C"

    def test_wrapper(self, tmp_path):
        p = tmp_path / "ports.json"
        p.write_text(json.dumps({"ports": [{"name": "C", "lat": 5, "lon": 5}]}), encoding="utf-8")
        assert len(load_ports(str(p))) == 1

    def test_defaults_filled(self, tmp_path):
        p = tmp_path / "ports.json"
        p.write_text(json.dumps([{"name": "C", "lat": 5, "lon": 5}]), encoding="utf-8")
        pt = load_ports(str(p))[0]
        assert pt["radius_nm"] == 8.0 and pt["risk"] == "normal"

    def test_missing_lat_clear_error(self, tmp_path):
        p = tmp_path / "ports.json"
        p.write_text(json.dumps([{"name": "C", "lon": 5}]), encoding="utf-8")
        with pytest.raises(ValueError, match="malformed"):
            load_ports(str(p))

    def test_non_numeric_lat(self, tmp_path):
        p = tmp_path / "ports.json"
        p.write_text(json.dumps([{"name": "C", "lat": "x", "lon": 5}]), encoding="utf-8")
        with pytest.raises(ValueError, match="malformed"):
            load_ports(str(p))

    def test_bad_json(self, tmp_path):
        p = tmp_path / "ports.json"
        p.write_text("[not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_ports(str(p))


class TestDetectPortCalls:
    def _kharg_then_singapore(self):
        recs = []
        for h in range(3):
            recs.append({"mmsi": "P1", "timestamp": f"2026-01-04T0{h}:00:00Z",
                         "lat": 29.23, "lon": 50.32, "name": "GREY"})
        for h in range(3):
            recs.append({"mmsi": "P1", "timestamp": f"2026-01-1{h}T00:00:00Z",
                         "lat": 1.264, "lon": 103.840, "name": "GREY"})
        return parse_messages(recs)

    def test_two_calls(self):
        calls = detect_port_calls(self._kharg_then_singapore())
        assert {c["port"] for c in calls} == {"Kharg Island", "Singapore"}

    def test_sanctioned_high_severity(self):
        calls = detect_port_calls(self._kharg_then_singapore())
        kharg = next(c for c in calls if c["port"] == "Kharg Island")
        assert kharg["risk"] == "sanctioned" and kharg["severity"] == "high"

    def test_high_risk_medium_severity(self):
        recs = [{"mmsi": "R", "timestamp": f"2026-01-04T0{h}:00:00Z",
                 "lat": 60.350, "lon": 28.690, "name": "T"} for h in range(3)]  # Primorsk
        c = detect_port_calls(parse_messages(recs))[0]
        assert c["risk"] == "high" and c["severity"] == "medium"

    def test_open_water_no_calls(self):
        recs = [{"mmsi": "O", "timestamp": f"2026-01-04T0{h}:00:00Z",
                 "lat": 0.0, "lon": 0.0} for h in range(3)]
        assert detect_port_calls(parse_messages(recs)) == []

    def test_min_dwell_filter(self):
        recs = [{"mmsi": "S", "timestamp": "2026-01-04T00:00:00Z", "lat": 29.23, "lon": 50.32}]
        # single ping: len(run) < 2 and dwell 0 < 1 -> dropped
        assert detect_port_calls(parse_messages(recs), min_dwell_hours=1.0) == []

    def test_custom_ports(self):
        recs = [{"mmsi": "C", "timestamp": f"2026-01-04T0{h}:00:00Z",
                 "lat": 5.0, "lon": 5.0, "name": "X"} for h in range(3)]
        custom = [{"name": "Custom", "country": "XX", "lat": 5.0, "lon": 5.0,
                   "radius_nm": 20, "risk": "sanctioned"}]
        calls = detect_port_calls(parse_messages(recs), ports=custom)
        assert calls[0]["port"] == "Custom" and calls[0]["risk"] == "sanctioned"

    def test_empty(self):
        assert detect_port_calls([]) == []


class TestSequenceItineraries:
    def _calls(self):
        recs = []
        for h in range(3):
            recs.append({"mmsi": "P1", "timestamp": f"2026-01-04T0{h}:00:00Z",
                         "lat": 29.23, "lon": 50.32, "name": "GREY"})
        for h in range(3):
            recs.append({"mmsi": "P1", "timestamp": f"2026-01-1{h}T00:00:00Z",
                         "lat": 1.264, "lon": 103.840, "name": "GREY"})
        return detect_port_calls(parse_messages(recs))

    def test_itinerary_ordered(self):
        its = sequence_itineraries(self._calls())
        assert its[0]["calls"] == ["Kharg Island", "Singapore"]

    def test_risk_leg_flagged(self):
        it = sequence_itineraries(self._calls())[0]
        assert it["legs"][0]["touches_risk_port"] is True

    def test_risk_ports_visited(self):
        it = sequence_itineraries(self._calls())[0]
        assert "Kharg Island" in it["risk_ports_visited"]
        assert it["severity"] == "high"

    def test_clean_itinerary_low(self):
        recs = [{"mmsi": "N", "timestamp": f"2026-01-04T0{h}:00:00Z",
                 "lat": 1.264, "lon": 103.840, "name": "CLEAN"} for h in range(3)]
        its = sequence_itineraries(detect_port_calls(parse_messages(recs)))
        assert its[0]["severity"] == "low"

    def test_empty(self):
        assert sequence_itineraries([]) == []

    def test_sorted_risky_first(self):
        recs = []
        # clean vessel
        for h in range(3):
            recs.append({"mmsi": "CLEAN", "timestamp": f"2026-01-04T0{h}:00:00Z",
                         "lat": 1.264, "lon": 103.840, "name": "C"})
        # risky vessel
        for h in range(3):
            recs.append({"mmsi": "RISK", "timestamp": f"2026-01-04T0{h}:00:00Z",
                         "lat": 29.23, "lon": 50.32, "name": "R"})
        its = sequence_itineraries(detect_port_calls(parse_messages(recs)))
        assert its[0]["mmsi"] == "RISK"
