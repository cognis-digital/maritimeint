"""Native, dependency-free intelligence export for maritimeint findings.

Turns the output of :func:`maritimeint.core.analyze` (or any ``{"findings": [...]}``
result) into standard, shareable formats — so a detection run becomes mappable,
SIEM-ingestible, and analyst-ready without installing anything:

* **GeoJSON** — drop findings straight onto a map (Leaflet/Mapbox/QGIS/kepler.gl).
* **KML**     — open in Google Earth / marine charting tools.
* **STIX 2.1**— a valid bundle of Indicator objects for threat-intel platforms.
* **CSV**     — flat tabular export for spreadsheets / notebooks.

This is intentionally separate from :mod:`maritimeint.connect` (which forwards a
*watchlist* via the optional ``cognis-connect`` SDK). ``intel`` is standard
library only, exports *every* detector's findings, and adds the geospatial
formats maritime analysts actually use.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

# Deterministic namespace so the same finding always yields the same STIX id.
_NS = uuid.UUID("6f9b1e2c-0000-4000-8000-636f676e6973")
_FALLBACK_TS = "2026-01-01T00:00:00.000Z"

# Keys whose value is a [lat, lon] pair, in priority order.
_POINT_KEYS = ("at", "where", "center", "centroid", "location", "position", "from", "to")


def _coords(f: dict[str, Any]) -> list[tuple[float, float]]:
    """Extract every (lat, lon) pair a finding carries, de-duplicated in order."""
    pts: list[tuple[float, float]] = []
    for key in _POINT_KEYS:
        v = f.get(key)
        if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
            pts.append((float(v[0]), float(v[1])))
    if isinstance(f.get("lat"), (int, float)) and isinstance(f.get("lon"), (int, float)):
        pts.append((float(f["lat"]), float(f["lon"])))
    seen = set()
    out = []
    for p in pts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _label(f: dict[str, Any]) -> str:
    who = f.get("name") or f.get("mmsi") or ",".join(f.get("vessels", [])) or "unknown"
    return f"{f.get('type', 'finding')}: {who}"


def _timestamp(f: dict[str, Any]) -> str:
    for k in ("timestamp", "dark_from", "start", "from_time", "time"):
        v = f.get(k)
        if isinstance(v, str) and v:
            return v if v.endswith("Z") else v.rstrip("Z") + "Z" if "T" in v else _FALLBACK_TS
    return _FALLBACK_TS


def _findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result, dict) and "findings" in result:
        return list(result["findings"])
    if isinstance(result, list):
        return list(result)
    raise ValueError("expected an analyze() result with a 'findings' list")


# --------------------------------------------------------------------------- #
# GeoJSON
# --------------------------------------------------------------------------- #
def to_geojson(result: dict[str, Any]) -> str:
    features = []
    for f in _findings(result):
        pts = _coords(f)
        # GeoJSON uses [lon, lat] order.
        if len(pts) >= 2:
            geometry = {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in pts]}
        elif len(pts) == 1:
            lat, lon = pts[0]
            geometry = {"type": "Point", "coordinates": [lon, lat]}
        else:
            geometry = None
        props = {k: v for k, v in f.items() if not isinstance(v, (list, dict)) or k in ("vessels",)}
        props["label"] = _label(f)
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    return json.dumps({"type": "FeatureCollection", "features": features}, indent=2)


# --------------------------------------------------------------------------- #
# KML
# --------------------------------------------------------------------------- #
def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def to_kml(result: dict[str, Any]) -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             '<name>maritimeint findings</name>']
    for f in _findings(result):
        pts = _coords(f)
        if not pts:
            continue
        name = _xml_escape(_label(f))
        desc = _xml_escape(f.get("detail", "") or f"severity={f.get('severity', 'n/a')}")
        if len(pts) >= 2:
            coords = " ".join(f"{lon},{lat},0" for lat, lon in pts)
            geom = f"<LineString><coordinates>{coords}</coordinates></LineString>"
        else:
            lat, lon = pts[0]
            geom = f"<Point><coordinates>{lon},{lat},0</coordinates></Point>"
        parts.append(f"<Placemark><name>{name}</name><description>{desc}</description>{geom}</Placemark>")
    parts.append("</Document></kml>")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# STIX 2.1
# --------------------------------------------------------------------------- #
def to_stix(result: dict[str, Any]) -> str:
    objects = []
    for f in _findings(result):
        seed = json.dumps(f, sort_keys=True, default=str)
        oid = f"indicator--{uuid.uuid5(_NS, seed)}"
        ts = _timestamp(f)
        mmsi = f.get("mmsi") or (f.get("vessels") or [""])[0]
        pattern = f"[x-maritime:mmsi = '{mmsi}']" if mmsi else "[x-maritime:event = 'true']"
        objects.append({
            "type": "indicator",
            "spec_version": "2.1",
            "id": oid,
            "created": ts,
            "modified": ts,
            "name": _label(f),
            "description": f.get("detail", "") or f"{f.get('type')} detected by maritimeint",
            "indicator_types": ["anomalous-activity"],
            "pattern": pattern,
            "pattern_type": "stix",
            "valid_from": ts,
            "labels": [str(f.get("severity", "low"))],
            "x_maritime": {k: v for k, v in f.items() if isinstance(v, (str, int, float, bool))},
        })
    bundle = {
        "type": "bundle",
        "id": f"bundle--{uuid.uuid5(_NS, json.dumps([o['id'] for o in objects]))}",
        "objects": objects,
    }
    return json.dumps(bundle, indent=2)


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def to_csv(result: dict[str, Any]) -> str:
    rows = _findings(result)
    fields = ["type", "severity", "mmsi", "name", "lat", "lon", "detail"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for f in rows:
        row = dict(f)
        pts = _coords(f)
        if pts and "lat" not in row:
            row["lat"], row["lon"] = pts[0]
        if not row.get("detail"):
            row["detail"] = f"{f.get('type')} ({f.get('severity', 'n/a')})"
        writer.writerow(row)
    return buf.getvalue()


_EXPORTERS = {"geojson": to_geojson, "kml": to_kml, "stix": to_stix, "csv": to_csv}


def export(result: dict[str, Any], fmt: str) -> str:
    fmt = fmt.lower()
    if fmt not in _EXPORTERS:
        raise ValueError(f"unknown export format {fmt!r}; choose one of {sorted(_EXPORTERS)}")
    return _EXPORTERS[fmt](result)
