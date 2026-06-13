"""Sanctions cross-reference for MARITIMEINT.

Cross-references tracked vessels against a sanctions list (OFAC SDN / EU / UK OFSI
style). Entries match by MMSI, IMO number, or vessel name. Designations list
vessels by IMO number, which is the durable, hull-bound identity (MMSI is
reassignable), so IMO is the strongest key when you have it.

A sanctions list is a JSON array of entries:
    {"name": "...", "imo": "9....", "mmsi": "2...", "program": "RUSSIA-EO14024", "source": "OFAC SDN"}

Pure standard library.
"""

from __future__ import annotations

import json
from typing import Any


def load_sanctions(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("sanctions list must be a JSON array")
    return data


def _norm(s: str | None) -> str:
    return (s or "").strip().upper()


def screen(mmsi: str, name: str = "", imo: str = "",
           sanctions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return sanctions entries that match this vessel, with what matched."""
    hits: list[dict[str, Any]] = []
    for entry in sanctions or []:
        matched = []
        if mmsi and _norm(entry.get("mmsi")) == _norm(mmsi):
            matched.append("mmsi")
        if imo and _norm(entry.get("imo")) == _norm(imo):
            matched.append("imo")
        if name and _norm(entry.get("name")) and _norm(entry.get("name")) == _norm(name):
            matched.append("name")
        if matched:
            hits.append({"matched_on": matched, "entry": entry})
    return hits
