"""Port-call sequencing for MARITIMEINT.

Infers *port calls* from AIS tracks — a vessel dwelling inside a port's radius is a
call — then sequences each vessel's calls into an itinerary and flags calls at
high-risk / sanctioned ports and suspicious dark legs between calls. Standard library.

Ships with a small built-in registry of real ports (including ones that recur in
sanctions-evasion reporting); pass a custom registry JSON to override/extend it:

    [{"name": "Kharg Island", "country": "IR", "lat": 29.23, "lon": 50.32,
      "radius_nm": 6, "risk": "sanctioned"}]
"""

from __future__ import annotations

import json
from typing import Any

from .core import AISMessage, haversine_nm, _by_vessel

# (name, country, lat, lon, radius_nm, risk)  -- risk in {"normal","high","sanctioned"}
_BUILTIN: list[tuple[str, str, float, float, float, str]] = [
    ("Singapore", "SG", 1.264, 103.840, 12.0, "normal"),
    ("Rotterdam", "NL", 51.949, 4.140, 12.0, "normal"),
    ("Fujairah", "AE", 25.112, 56.350, 10.0, "normal"),
    ("Ningbo-Zhoushan", "CN", 29.870, 122.070, 12.0, "normal"),
    ("Houston", "US", 29.726, -95.073, 12.0, "normal"),
    ("Kharg Island", "IR", 29.230, 50.320, 8.0, "sanctioned"),
    ("Bandar Abbas", "IR", 27.150, 56.210, 8.0, "sanctioned"),
    ("Primorsk", "RU", 60.350, 28.690, 8.0, "high"),
    ("Ust-Luga", "RU", 59.670, 28.410, 8.0, "high"),
    ("Nakhodka", "RU", 42.810, 132.880, 8.0, "high"),
    ("Tartus", "SY", 34.890, 35.870, 6.0, "sanctioned"),
    ("Nampo", "KP", 38.710, 125.380, 8.0, "sanctioned"),
]


def _port(rec: tuple) -> dict[str, Any]:
    name, country, lat, lon, radius, risk = rec
    return {"name": name, "country": country, "lat": lat, "lon": lon,
            "radius_nm": radius, "risk": risk}


def builtin_ports() -> list[dict[str, Any]]:
    return [_port(r) for r in _BUILTIN]


def load_ports(path: str) -> list[dict[str, Any]]:
    """Load a custom port registry (list or `{"ports": [...]}`)."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, dict):
        raw = raw.get("ports", [])
    if not isinstance(raw, list):
        raise ValueError("port registry must be a list or {'ports': [...]}")
    ports = []
    for i, p in enumerate(raw):
        try:
            ports.append({
                "name": str(p["name"]),
                "country": str(p.get("country", "")),
                "lat": float(p["lat"]),
                "lon": float(p["lon"]),
                "radius_nm": float(p.get("radius_nm", 8.0)),
                "risk": str(p.get("risk", "normal")),
            })
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"port registry entry #{i} is malformed "
                f"(needs name/lat/lon): {exc}"
            ) from exc
    return ports


def _nearest_port(lat: float, lon: float, ports: list[dict[str, Any]]):
    """Nearest port whose radius contains the point, else None."""
    best = None
    for p in ports:
        d = haversine_nm(lat, lon, p["lat"], p["lon"])
        if d <= p["radius_nm"] and (best is None or d < best[1]):
            best = (p, d)
    return best[0] if best else None


def detect_port_calls(
    msgs: list[AISMessage],
    ports: list[dict[str, Any]] | None = None,
    min_dwell_hours: float = 1.0,
) -> list[dict[str, Any]]:
    """Per vessel, detect dwell-based port calls (arrive/depart/dwell, risk-tagged)."""
    ports = ports if ports is not None else builtin_ports()
    calls: list[dict[str, Any]] = []
    for mmsi, track in _by_vessel(msgs).items():
        cur_port: str | None = None
        run: list[AISMessage] = []

        def flush(port_name, run):
            if not port_name or not run:
                return
            dwell_h = (run[-1].timestamp - run[0].timestamp).total_seconds() / 3600.0
            if dwell_h < min_dwell_hours and len(run) < 2:
                return
            p = next(pp for pp in ports if pp["name"] == port_name)
            sev = "high" if p["risk"] == "sanctioned" else \
                "medium" if p["risk"] == "high" else "low"
            calls.append({
                "type": "port_call",
                "mmsi": mmsi,
                "name": run[0].name or track[0].name,
                "port": port_name,
                "country": p["country"],
                "risk": p["risk"],
                "arrive": run[0].timestamp.isoformat().replace("+00:00", "Z"),
                "depart": run[-1].timestamp.isoformat().replace("+00:00", "Z"),
                "dwell_hours": round(dwell_h, 2),
                "reports": len(run),
                "severity": sev,
            })

        for m in track:
            pn = (_nearest_port(m.lat, m.lon, ports) or {}).get("name")
            if pn == cur_port:
                if pn:
                    run.append(m)
            else:
                flush(cur_port, run)
                cur_port = pn
                run = [m] if pn else []
        flush(cur_port, run)
    return calls


def sequence_itineraries(
    calls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Group port calls per vessel into an ordered itinerary with legs.

    A "dark leg" flag is set when consecutive calls touch a sanctioned/high-risk
    port — the classic laundering pattern (load at a sanctioned port, sail to a
    clean hub to sell)."""
    by_vessel: dict[str, list[dict[str, Any]]] = {}
    for c in calls:
        by_vessel.setdefault(c["mmsi"], []).append(c)
    itineraries: list[dict[str, Any]] = []
    for mmsi, vcalls in by_vessel.items():
        vcalls.sort(key=lambda c: c["arrive"])
        legs = []
        for a, b in zip(vcalls, vcalls[1:]):
            risky = a["risk"] in ("sanctioned", "high") or b["risk"] in ("sanctioned", "high")
            legs.append({
                "from": a["port"], "to": b["port"],
                "depart": a["depart"], "arrive": b["arrive"],
                "touches_risk_port": risky,
            })
        touched = sorted({c["port"] for c in vcalls if c["risk"] in ("sanctioned", "high")})
        itineraries.append({
            "type": "itinerary",
            "mmsi": mmsi,
            "name": vcalls[0]["name"],
            "calls": [c["port"] for c in vcalls],
            "risk_ports_visited": touched,
            "legs": legs,
            "severity": "high" if touched else "low",
        })
    itineraries.sort(key=lambda it: (bool(it["risk_ports_visited"]), len(it["calls"])),
                     reverse=True)
    return itineraries
