"""Edge-case tests for maritimeint.sanctions_sources (OFAC/OFSI/EU/OpenSanctions + merge)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint import sanctions_sources as SS  # noqa: E402
from maritimeint import ofac as OFAC  # noqa: E402


OFAC_ROW = ('1,"GREY GHOST",vessel,IRAN,-0-,ABCD,Crude Oil Tanker,-0-,-0-,None,'
            '-0-,"Vessel Registration IMO 9176187; MMSI 477000001."')


class TestOfacParser:
    def test_vessel_row(self):
        out = OFAC.parse_sdn_csv(OFAC_ROW + "\n")
        assert out[0]["imo"] == "9176187" and out[0]["mmsi"] == "477000001"

    def test_non_vessel_skipped(self):
        row = '2,"SOME PERSON",individual,IRAN,-0-,-0-,-0-,-0-,-0-,-0-,-0-,"person"'
        assert OFAC.parse_sdn_csv(row + "\n") == []

    def test_short_row_skipped(self):
        assert OFAC.parse_sdn_csv("1,short,row\n") == []

    def test_empty(self):
        assert OFAC.parse_sdn_csv("") == []

    def test_dash_zero_cleaned(self):
        out = OFAC.parse_sdn_csv(OFAC_ROW + "\n")
        assert out[0]["source"] == "OFAC SDN"


class TestOfsiParser:
    def test_ship_row(self):
        csv = ("Group Type,Name 1,Regime,Flag,Other\n"
               "Ship,SHADOW STAR,RUSSIA,PA,IMO 9111111\n")
        out = SS.parse_ofsi_csv(csv)
        assert out and out[0]["imo"] == "9111111" and out[0]["source"] == "UK OFSI"

    def test_non_ship_skipped(self):
        csv = "Group Type,Name 1\nEntity,SOME CORP\n"
        assert SS.parse_ofsi_csv(csv) == []

    def test_banner_line_before_header(self):
        csv = ("UK Sanctions List - generated 2026\n"
               "Group Type,Name 1,Other\n"
               "Ship,VESSEL X,IMO 9222222\n")
        out = SS.parse_ofsi_csv(csv)
        assert out and out[0]["imo"] == "9222222"


class TestEuParser:
    def test_vessel_entity(self):
        xml = """<?xml version="1.0"?>
        <export>
          <sanctionEntity>
            <subjectType code="vessel"/>
            <nameAlias wholeName="EU SHIP"/>
            <identification identificationTypeCode="imo" number="9333333"/>
          </sanctionEntity>
        </export>"""
        out = SS.parse_eu_xml(xml)
        assert out and out[0]["name"] == "EU SHIP" and out[0]["imo"] == "9333333"

    def test_non_vessel_skipped(self):
        xml = """<?xml version="1.0"?>
        <export><sanctionEntity><subjectType code="person"/></sanctionEntity></export>"""
        assert SS.parse_eu_xml(xml) == []

    def test_bad_xml_returns_empty(self):
        assert SS.parse_eu_xml("<not valid") == []


class TestOpenSanctionsParser:
    def test_vessel_jsonl(self):
        import json
        line = json.dumps({"schema": "Vessel", "caption": "OS SHIP",
                           "properties": {"name": ["OS SHIP"], "imoNumber": ["9444444"],
                                          "mmsi": ["538000001"], "program": ["EU.SANC"]}})
        out = SS.parse_opensanctions_jsonl(line)
        assert out[0]["imo"] == "9444444" and out[0]["mmsi"] == "538000001"

    def test_non_vessel_skipped(self):
        import json
        line = json.dumps({"schema": "Person", "caption": "X", "properties": {}})
        assert SS.parse_opensanctions_jsonl(line) == []

    def test_blank_lines_ignored(self):
        assert SS.parse_opensanctions_jsonl("\n\n  \n") == []

    def test_bad_json_line_skipped(self):
        assert SS.parse_opensanctions_jsonl("{not json\n") == []


class TestParseDispatch:
    def test_known_source(self):
        assert SS.parse("ofac", OFAC_ROW + "\n")[0]["imo"] == "9176187"

    def test_unknown_source(self):
        with pytest.raises(ValueError, match="unknown sanctions source"):
            SS.parse("nosuch", "")


class TestFetch:
    def test_unknown_source_no_url(self):
        with pytest.raises(ValueError, match="no default URL"):
            SS.fetch("ofsi")


class TestMerge:
    def test_dedup_by_imo(self):
        a = [SS._entry("SHIP A", imo="9111111", source="OFAC", program="IRAN")]
        b = [SS._entry("SHIP A ALIAS", imo="9111111", source="EU", program="EU")]
        merged = SS.merge(a, b)
        assert len(merged) == 1
        assert "OFAC" in merged[0]["source"] and "EU" in merged[0]["source"]

    def test_dedup_by_mmsi(self):
        a = [SS._entry("X", mmsi="273000001", source="OFAC")]
        b = [SS._entry("Y", mmsi="273000001", source="OpenSanctions")]
        assert len(SS.merge(a, b)) == 1

    def test_dedup_by_name(self):
        a = [SS._entry("SAME NAME", source="OFAC")]
        b = [SS._entry("same name", source="EU")]
        assert len(SS.merge(a, b)) == 1

    def test_distinct_kept(self):
        a = [SS._entry("SHIP A", imo="9111111")]
        b = [SS._entry("SHIP B", imo="9222222")]
        assert len(SS.merge(a, b)) == 2

    def test_nameless_entry_dropped(self):
        assert SS.merge([SS._entry("")]) == []

    def test_fills_missing_fields(self):
        a = [SS._entry("SHIP", imo="9111111")]  # no mmsi
        b = [SS._entry("SHIP", imo="9111111", mmsi="273000001", flag="PA")]
        merged = SS.merge(a, b)
        assert merged[0]["mmsi"] == "273000001" and merged[0]["flag"] == "PA"

    def test_empty(self):
        assert SS.merge() == []


class TestParsersRegistry:
    def test_all_sources_registered(self):
        assert set(SS.PARSERS) == {"ofac", "ofsi", "eu", "opensanctions"}
