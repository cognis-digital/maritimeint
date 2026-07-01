"""End-to-end CLI edge/error-path tests (maritimeint.cli.main). No network."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.cli import main, build_parser  # noqa: E402


RECS = [
    {"mmsi": "A1", "timestamp": "2026-01-04T00:00:00Z", "lat": 26.0, "lon": 52.0, "name": "DARK"},
    {"mmsi": "A1", "timestamp": "2026-01-04T12:00:00Z", "lat": 26.5, "lon": 52.5, "name": "DARK"},
    {"mmsi": "B1", "timestamp": "2026-01-04T03:00:00Z", "lat": 26.02, "lon": 52.02, "name": "LIGHTER"},
    {"mmsi": "B1", "timestamp": "2026-01-04T04:00:00Z", "lat": 26.01, "lon": 52.01, "name": "LIGHTER"},
]
ZONES = [{"name": "Z", "kind": "eez",
          "polygon": [[51.0, 25.0], [53.0, 25.0], [53.0, 27.0], [51.0, 27.0]]}]
SDN = [{"name": "DARK", "mmsi": "A1", "imo": "", "program": "TEST", "source": "TEST"}]


@pytest.fixture
def feed(tmp_path):
    p = tmp_path / "feed.json"
    p.write_text(json.dumps({"messages": RECS}), encoding="utf-8")
    return str(p)


@pytest.fixture
def zonef(tmp_path):
    p = tmp_path / "zones.json"
    p.write_text(json.dumps(ZONES), encoding="utf-8")
    return str(p)


@pytest.fixture
def sdnf(tmp_path):
    p = tmp_path / "sdn.json"
    p.write_text(json.dumps(SDN), encoding="utf-8")
    return str(p)


class TestParser:
    def test_builds(self):
        assert build_parser() is not None

    def test_requires_command(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args([])


class TestBasicCommands:
    @pytest.mark.parametrize("cmd", ["analyze", "gaps", "jumps", "loiter", "spoof",
                                     "rendezvous", "dark-rendezvous", "gps",
                                     "close-quarters", "shadowing", "convoy", "drift",
                                     "encounters"])
    def test_command_exits_zero(self, cmd, feed):
        assert main([cmd, feed]) == 0

    @pytest.mark.parametrize("cmd", ["analyze", "gaps", "jumps", "gps", "encounters"])
    def test_json_format(self, cmd, feed, capsys):
        assert main(["--format", "json", cmd, feed]) == 0
        out = capsys.readouterr().out
        json.loads(out)  # valid JSON

    def test_analyze_with_zones(self, feed, zonef):
        assert main(["--format", "json", "analyze", feed, "--zones", zonef]) == 0

    def test_zones_command(self, feed, zonef):
        assert main(["zones", feed, "--zones", zonef]) == 0

    def test_port_calls(self, feed):
        assert main(["port-calls", feed]) == 0

    def test_port_calls_itinerary(self, feed):
        assert main(["port-calls", feed, "--itinerary"]) == 0

    def test_gaps_threshold(self, feed):
        assert main(["gaps", feed, "--gap-hours", "24"]) == 0

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as ei:
            main(["--version"])
        assert ei.value.code == 0


class TestLocate:
    def test_basic(self, feed):
        assert main(["locate", feed]) == 0

    def test_json(self, feed, capsys):
        assert main(["--format", "json", "locate", feed]) == 0
        assert "watchlist" in json.loads(capsys.readouterr().out)

    def test_with_sanctions(self, feed, sdnf):
        assert main(["locate", feed, "--sanctions", sdnf]) == 0

    def test_with_zones(self, feed, zonef):
        assert main(["locate", feed, "--zones", zonef]) == 0

    def test_fail_on_high_triggers(self, feed, sdnf):
        # A1 is sanctioned -> HIGH tier -> exit 2
        assert main(["locate", feed, "--sanctions", sdnf, "--fail-on", "high"]) == 2

    def test_ai_no_backend_message(self, feed, capsys):
        assert main(["locate", feed, "--ai"]) == 0

    def test_emit_dry_run(self, feed, sdnf, capsys):
        rc = main(["--format", "json", "locate", feed, "--sanctions", sdnf,
                   "--emit", "stix", "--emit-dry-run"])
        assert rc in (0, 1)  # dry-run preview or a clean connect error


class TestExport:
    @pytest.mark.parametrize("fmt", ["geojson", "kml", "stix", "csv"])
    def test_stdout(self, fmt, feed, capsys):
        assert main(["export", feed, "--to", fmt]) == 0
        assert len(capsys.readouterr().out) > 0

    def test_to_file(self, feed, tmp_path):
        out = tmp_path / "out.geojson"
        assert main(["export", feed, "--to", "geojson", "-o", str(out)]) == 0
        assert out.exists() and out.read_text(encoding="utf-8").strip()

    def test_export_with_zones(self, feed, zonef):
        assert main(["export", feed, "--to", "geojson", "--zones", zonef]) == 0


class TestErrorPaths:
    def test_missing_file(self, tmp_path, capsys):
        assert main(["analyze", str(tmp_path / "nope.json")]) == 1
        assert "error" in capsys.readouterr().err.lower()

    def test_bad_json(self, tmp_path, capsys):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        assert main(["analyze", str(p)]) == 1
        assert "error" in capsys.readouterr().err.lower()

    def test_malformed_record(self, tmp_path, capsys):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps([{"mmsi": "X"}]), encoding="utf-8")  # missing fields
        assert main(["analyze", str(p)]) == 1

    def test_out_of_range_lat(self, tmp_path, capsys):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps([{"mmsi": "X", "timestamp": "2026-01-04T00:00:00Z",
                                  "lat": 200, "lon": 5}]), encoding="utf-8")
        assert main(["analyze", str(p)]) == 1
        assert "lat" in capsys.readouterr().err

    def test_bad_timestamp(self, tmp_path, capsys):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps([{"mmsi": "X", "timestamp": "nope", "lat": 5, "lon": 5}]),
                     encoding="utf-8")
        assert main(["analyze", str(p)]) == 1

    def test_zones_requires_zonefile(self, feed):
        with pytest.raises(SystemExit):
            main(["zones", feed])  # --zones is required

    def test_missing_zone_file(self, feed, tmp_path, capsys):
        assert main(["zones", feed, "--zones", str(tmp_path / "nope.json")]) == 1


class TestAddinsAndFetchErrors:
    def test_addins_table(self, capsys):
        assert main(["addins"]) == 0
        assert "add-ins" in capsys.readouterr().out.lower()

    def test_addins_json(self, capsys):
        assert main(["--format", "json", "addins"]) == 0
        json.loads(capsys.readouterr().out)

    def test_fetch_ais_file_requires_from_file(self, capsys):
        assert main(["fetch-ais", "--source", "file"]) == 1

    def test_fetch_ais_aishub_requires_username(self, capsys):
        assert main(["fetch-ais", "--source", "aishub"]) == 1

    def test_fetch_ais_file(self, tmp_path, capsys):
        src = tmp_path / "prov.csv"
        src.write_text("mmsi,latitude,longitude,time\n1,26.0,52.0,2026-01-04T00:00:00Z\n",
                       encoding="utf-8")
        out = tmp_path / "ais.json"
        assert main(["fetch-ais", "--source", "file", "--from-file", str(src),
                     "--out", str(out)]) == 0
        assert out.exists()

    def test_import_ofac_from_file(self, tmp_path, capsys):
        # a minimal SDN.csv vessel row (12 fields)
        row = ("1,\"GREY GHOST\",vessel,IRAN,-0-,ABCD,Crude Oil Tanker,-0-,-0-,None,"
               "-0-,\"Vessel Registration IMO 9176187; MMSI 477000001.\"")
        src = tmp_path / "sdn.csv"
        src.write_text(row + "\n", encoding="utf-8")
        out = tmp_path / "s.json"
        assert main(["import-ofac", "--from-file", str(src), "--out", str(out)]) == 0
        entries = json.loads(out.read_text(encoding="utf-8"))
        assert entries and entries[0]["imo"] == "9176187"
