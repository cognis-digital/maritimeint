"""Multi-source sanctioned-vessel importers — real designation lists, one format.

Adapters for the major public vessel-designation sources, each parsing the source's
*real* published format into maritimeint's `--sanctions` entry shape
(`{name, imo, mmsi, program, source, flag, call_sign}`), plus `merge()` to combine +
de-duplicate across sources (by IMO, else MMSI, else normalized name):

  ofac          OFAC SDN.csv                     (see maritimeint.ofac)
  ofsi          UK OFSI consolidated list CSV     (Group Type "Ship")
  eu            EU consolidated list XML          (vessel subject type)
  opensanctions OpenSanctions FtM JSONL           (schema == "Vessel") — aggregates OFAC/EU/UK/UN

Endpoints for OFSI/EU shift and EU now gates its web service, so those adapters also
accept a downloaded file (`--from-file`). OpenSanctions bulk data is open and is the
most reliable single multi-source feed. Pure standard library.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.request
import xml.etree.ElementTree as ET

from maritimeint.ofac import parse_sdn_csv  # OFAC adapter

_IMO = re.compile(r"\b(?:IMO\s*[:#]?\s*)?(\d{7})\b")
_IMO_LABELLED = re.compile(r"\bIMO\s*[:#]?\s*(\d{7})\b", re.I)
_MMSI = re.compile(r"\bMMSI\s*[:#]?\s*(\d{9})\b", re.I)

SOURCES = {
    "ofac": "https://www.treasury.gov/ofac/downloads/sdn.csv",
    "opensanctions": "https://data.opensanctions.org/datasets/latest/sanctions/entities.ftm.json",
    # OFSI/EU URLs drift / may require a token — pass --from-file. Documented in SOURCES.md.
}


def _entry(name, imo="", mmsi="", program="", source="", flag="", call_sign=""):
    return {"name": name, "imo": imo, "mmsi": mmsi, "program": program,
            "source": source, "flag": flag, "call_sign": call_sign}


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# --- UK OFSI consolidated list (CSV) -----------------------------------------
def parse_ofsi_csv(text: str) -> list[dict]:
    """OFSI ConList.csv: keep 'Ship' group-type rows, pull IMO from the row text."""
    lines = text.splitlines()
    # the first line is often a title/date banner; the real header has 'Group Type'
    start = 0
    for i, ln in enumerate(lines[:3]):
        if "group type" in ln.lower():
            start = i
            break
    rdr = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    out = []
    for row in rdr:
        gt = (row.get("Group Type") or row.get("GroupType") or "").strip().lower()
        if "ship" not in gt:
            continue
        blob = " ".join(v for v in row.values() if v)
        name = (row.get("Name 1") or row.get("Name") or "").strip()
        for k in ("Name 2", "Name 3", "Name 4", "Name 5", "Name 6"):
            if row.get(k):
                name = (name + " " + row[k]).strip()
        imo = _IMO_LABELLED.search(blob)
        out.append(_entry(name, imo.group(1) if imo else "",
                          program=(row.get("Regime") or "UK OFSI").strip(),
                          source="UK OFSI", flag=(row.get("Flag") or "").strip()))
    return out


# --- EU consolidated list (XML) ----------------------------------------------
def parse_eu_xml(text: str) -> list[dict]:
    """EU consolidated list XML: vessel entities + their IMO identification."""
    out = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return out
    for ent in root.iter():
        if _localname(ent.tag).lower() != "sanctionentity":
            continue
        subj = ""
        for ch in ent.iter():
            if _localname(ch.tag).lower() == "subjecttype":
                subj = (ch.get("code") or ch.get("classificationCode") or "").lower()
        if "vessel" not in subj and "ship" not in subj:
            continue
        name = ""
        imo = ""
        for ch in ent.iter():
            ln = _localname(ch.tag).lower()
            if ln in ("namealias", "wholename") and not name:
                name = (ch.get("wholeName") or (ch.text or "")).strip()
            blob = " ".join(filter(None, [ch.get("identificationTypeCode", ""),
                                          ch.get("number", ""), ch.text or ""]))
            m = _IMO_LABELLED.search(blob) or (_IMO.search(ch.get("number", "")) if "imo" in (ch.get("identificationTypeCode", "") or "").lower() else None)
            if m and not imo:
                imo = m.group(1)
        out.append(_entry(name, imo, program="EU", source="EU consolidated"))
    return out


# --- OpenSanctions (FtM JSONL) — aggregates OFAC/EU/UK/UN --------------------
def parse_opensanctions_jsonl(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ent = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ent.get("schema") != "Vessel":
            continue
        p = ent.get("properties", {})

        def first(key):
            v = p.get(key)
            return v[0] if isinstance(v, list) and v else ""
        out.append(_entry(first("name") or ent.get("caption", ""),
                          imo=first("imoNumber"), mmsi=first("mmsi"),
                          program=", ".join(p.get("program", []))[:120] or "OpenSanctions",
                          source="OpenSanctions", flag=first("flag")))
    return out


PARSERS = {"ofac": parse_sdn_csv, "ofsi": parse_ofsi_csv,
           "eu": parse_eu_xml, "opensanctions": parse_opensanctions_jsonl}


def fetch(source: str, timeout: float = 90.0) -> str:
    if source not in SOURCES:
        raise ValueError(f"no default URL for {source!r}; pass --from-file")
    with urllib.request.urlopen(SOURCES[source], timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse(source: str, text: str) -> list[dict]:
    if source not in PARSERS:
        raise ValueError(f"unknown sanctions source {source!r}; expected {sorted(PARSERS)}")
    return PARSERS[source](text)


def merge(*lists: list[dict]) -> list[dict]:
    """Combine entries, de-duping by IMO, else MMSI, else normalized name.
    On a dup, union the source/program so you can see every list a vessel is on."""
    by_key: dict[str, dict] = {}
    for entries in lists:
        for e in entries:
            key = ("imo:" + e["imo"]) if e.get("imo") else \
                  ("mmsi:" + e["mmsi"]) if e.get("mmsi") else \
                  ("name:" + (e.get("name") or "").upper().strip())
            if not key or key in ("name:",):
                continue
            if key in by_key:
                ex = by_key[key]
                for f in ("source", "program"):
                    parts = [x for x in (ex.get(f, ""), e.get(f, "")) if x]
                    ex[f] = " | ".join(sorted(set("; ".join(parts).split("; ")))) if parts else ""
                for f in ("imo", "mmsi", "flag", "call_sign"):
                    if not ex.get(f) and e.get(f):
                        ex[f] = e[f]
            else:
                by_key[key] = dict(e)
    return list(by_key.values())
