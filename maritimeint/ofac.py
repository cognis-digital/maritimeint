"""OFAC SDN importer — turn the real US Treasury sanctions list into maritimeint's
`--sanctions` format, so screening runs against actual designations.

Source: OFAC's published SDN.CSV (https://www.treasury.gov/ofac/downloads/sdn.csv).
The legacy SDN.CSV has 12 unlabelled fields per row; vessels have SDN_Type "vessel".
We keep the vessel rows and pull the IMO / MMSI / call sign out of the Remarks field
(OFAC records vessel IMO numbers in Remarks, e.g. "...IMO 9176187; MMSI 477...").

Output entries match maritimeint.sanctions:
    {"name","imo","mmsi","program","source","flag","call_sign"}

Network is optional: pass a local file with --from-file for offline/CI use. Pure stdlib.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.request

SDN_CSV_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"

# OFAC SDN.CSV column order (no header row). Empty cells are the literal "-0-".
_COLS = ["ent_num", "name", "sdn_type", "program", "title", "call_sign",
         "vess_type", "tonnage", "grt", "flag", "owner", "remarks"]

_IMO = re.compile(r"\bIMO\s*[:#]?\s*(\d{7})\b", re.I)
_MMSI = re.compile(r"\bMMSI\s*[:#]?\s*(\d{9})\b", re.I)


def _clean(v: str) -> str:
    v = (v or "").strip()
    return "" if v == "-0-" else v


def fetch_sdn(url: str = SDN_CSV_URL, timeout: float = 60.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_sdn_csv(text: str) -> list[dict]:
    """Parse SDN.CSV text into maritimeint sanctions entries (vessels only)."""
    out: list[dict] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < len(_COLS):
            continue
        rec = {c: _clean(row[i]) for i, c in enumerate(_COLS)}
        if rec["sdn_type"].lower() != "vessel":
            continue
        remarks = rec["remarks"]
        imo = (_IMO.search(remarks) or _IMO.search(rec["call_sign"]))
        mmsi = _MMSI.search(remarks)
        out.append({
            "name": rec["name"],
            "imo": imo.group(1) if imo else "",
            "mmsi": mmsi.group(1) if mmsi else "",
            "program": rec["program"],
            "source": "OFAC SDN",
            "flag": rec["flag"],
            "call_sign": rec["call_sign"],
        })
    return out


def to_sanctions(text: str) -> list[dict]:
    return parse_sdn_csv(text)


def write_sanctions(entries: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
