"""Zone intelligence (geofencing) for MARITIMEINT.

Adds the *spatial* dimension the detectors were missing: *where* an event happens
relative to areas an analyst cares about — EEZs, sanctioned ports, exclusion /
war-risk zones, fishing-restricted areas. Pure standard library.

A zone is a named area with a ``kind`` (free-text, e.g. ``"sanctioned_port"``,
``"eez"``, ``"exclusion"``, ``"war_risk"``). Two geometries are supported:

* **polygon** — a ring of ``[lon, lat]`` vertices (GeoJSON ordering).
* **circle**  — a ``center`` ``[lon, lat]`` plus ``radius_nm`` (handy for ports).

Zones load from GeoJSON (``FeatureCollection`` / ``Feature`` / bare geometry, with
``properties.name`` / ``properties.kind``) or from the simpler native list form::

    [{"name": "Kharg Island", "kind": "sanctioned_port",
      "center": [50.32, 29.23], "radius_nm": 5},
     {"name": "Persian Gulf EEZ", "kind": "eez",
      "polygon": [[48.0, 26.0], [56.0, 26.0], [56.0, 30.5], [48.0, 30.5]]}]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from .core import AISMessage, haversine_nm, _by_vessel


@dataclass
class Zone:
    name: str
    kind: str = "zone"
    polygon: list[tuple[float, float]] = field(default_factory=list)  # (lon, lat)
    center: tuple[float, float] | None = None  # (lon, lat)
    radius_nm: float | None = None

    def contains(self, lat: float, lon: float) -> bool:
        if self.center is not None and self.radius_nm is not None:
            return haversine_nm(lat, lon, self.center[1], self.center[0]) <= self.radius_nm
        if self.polygon:
            return _point_in_ring(lon, lat, self.polygon)
        return False


def _point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon. ``ring`` is (lon, lat); point is (x=lon, y=lat).

    Boundary points count as inside. The ring need not repeat its first vertex.
    """
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        # on a horizontal-crossing edge?
        if ((yi > y) != (yj > y)):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x_cross == x:
                return True  # exactly on edge
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _coerce_zone(d: dict[str, Any]) -> Zone:
    """Build a Zone from a native dict or a GeoJSON Feature/geometry."""
    # GeoJSON Feature -> unwrap geometry + properties
    if d.get("type") == "Feature":
        props = d.get("properties") or {}
        geom = d.get("geometry") or {}
        name = str(props.get("name", props.get("NAME", "zone")))
        kind = str(props.get("kind", props.get("type", "zone")))
        return _coerce_geometry(geom, name, kind)
    if d.get("type") in ("Polygon", "MultiPolygon", "Point"):
        return _coerce_geometry(d, str(d.get("name", "zone")), str(d.get("kind", "zone")))
    # native form
    name = str(d.get("name", "zone"))
    kind = str(d.get("kind", "zone"))
    z = Zone(name=name, kind=kind)
    if d.get("polygon"):
        z.polygon = [(float(p[0]), float(p[1])) for p in d["polygon"]]
    if d.get("center") is not None and d.get("radius_nm") is not None:
        c = d["center"]
        z.center = (float(c[0]), float(c[1]))
        z.radius_nm = float(d["radius_nm"])
    return z


def _coerce_geometry(geom: dict[str, Any], name: str, kind: str) -> Zone:
    gtype = geom.get("type")
    coords = geom.get("coordinates", [])
    if gtype == "Polygon":
        ring = coords[0] if coords else []
        return Zone(name=name, kind=kind,
                    polygon=[(float(p[0]), float(p[1])) for p in ring])
    if gtype == "MultiPolygon":
        # use the first polygon's outer ring (analysts split multipart zones by name)
        ring = coords[0][0] if coords and coords[0] else []
        return Zone(name=name, kind=kind,
                    polygon=[(float(p[0]), float(p[1])) for p in ring])
    if gtype == "Point":
        return Zone(name=name, kind=kind,
                    center=(float(coords[0]), float(coords[1])), radius_nm=1.0)
    return Zone(name=name, kind=kind)


def load_zones(path: str) -> list[Zone]:
    """Load zones from a GeoJSON file or the native list/`{"zones": [...]}` form."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return parse_zones(raw)


def parse_zones(raw: Any) -> list[Zone]:
    if isinstance(raw, dict):
        if raw.get("type") == "FeatureCollection":
            raw = raw.get("features", [])
        elif "zones" in raw:
            raw = raw["zones"]
        elif raw.get("type") in ("Feature", "Polygon", "MultiPolygon", "Point"):
            raw = [raw]
        else:
            raise ValueError("zone input must be GeoJSON or a list of zones")
    if not isinstance(raw, list):
        raise ValueError("zone input must be a list or GeoJSON FeatureCollection")
    return [_coerce_zone(d) for d in raw]


def zones_for_point(lat: float, lon: float, zones: list[Zone]) -> list[str]:
    """Names of every zone containing the point (a point can be in several)."""
    return [z.name for z in zones if z.contains(lat, lon)]


def detect_zone_transits(
    msgs: list[AISMessage], zones: list[Zone]
) -> list[dict[str, Any]]:
    """Per vessel, per zone: entry/exit events and total dwell time.

    A "visit" is a maximal run of consecutive reports inside the zone. Crossing in
    and out is reported as one visit with enter/exit timestamps and dwell hours.
    """
    findings: list[dict[str, Any]] = []
    for mmsi, track in _by_vessel(msgs).items():
        for z in zones:
            inside_runs: list[list[AISMessage]] = []
            cur: list[AISMessage] = []
            for m in track:
                if z.contains(m.lat, m.lon):
                    cur.append(m)
                elif cur:
                    inside_runs.append(cur)
                    cur = []
            if cur:
                inside_runs.append(cur)
            for run in inside_runs:
                dwell_h = (run[-1].timestamp - run[0].timestamp).total_seconds() / 3600.0
                sev = "high" if z.kind in ("sanctioned_port", "exclusion", "war_risk") \
                    else "medium" if z.kind == "eez" else "low"
                findings.append({
                    "type": "zone_transit",
                    "mmsi": mmsi,
                    "name": run[0].name or track[0].name,
                    "zone": z.name,
                    "zone_kind": z.kind,
                    "enter": run[0].timestamp.isoformat().replace("+00:00", "Z"),
                    "exit": run[-1].timestamp.isoformat().replace("+00:00", "Z"),
                    "dwell_hours": round(dwell_h, 2),
                    "reports": len(run),
                    "severity": sev,
                })
    return findings


def _positions_of(f: dict[str, Any]) -> list[tuple[float, float]]:
    """Pull every (lat, lon) point a finding references, for zone tagging."""
    pts: list[tuple[float, float]] = []
    for key in ("from", "to", "center", "position"):
        v = f.get(key)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            pts.append((float(v[0]), float(v[1])))
    return pts


def annotate_findings(
    findings: list[dict[str, Any]], zones: list[Zone]
) -> list[dict[str, Any]]:
    """Tag each finding with the zones its position(s) fall in (in place)."""
    for f in findings:
        names: list[str] = []
        for lat, lon in _positions_of(f):
            for n in zones_for_point(lat, lon, zones):
                if n not in names:
                    names.append(n)
        if names:
            f["zones"] = names
    return findings
