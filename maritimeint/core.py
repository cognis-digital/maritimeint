"""Core AIS analysis engine for MARITIMEINT.

Works on AIS position-report records. Each record is a dict with:
    mmsi      : str  -- Maritime Mobile Service Identity (vessel id)
    name      : str  -- (optional) reported vessel name
    timestamp : str  -- ISO-8601 UTC, e.g. "2026-01-04T12:00:00Z"
    lat       : float
    lon       : float
    sog       : float -- (optional) speed over ground, knots
    cog       : float -- (optional) course over ground, degrees

All detectors return plain dicts/lists so output serializes cleanly to JSON.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

EARTH_RADIUS_NM = 3440.065  # nautical miles


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class AISMessage:
    mmsi: str
    timestamp: datetime
    lat: float
    lon: float
    name: str = ""
    sog: float | None = None
    cog: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AISMessage":
        if "mmsi" not in d:
            raise ValueError("AIS record missing 'mmsi'")
        for key in ("timestamp", "lat", "lon"):
            if key not in d:
                raise ValueError(f"AIS record for {d.get('mmsi')} missing '{key}'")
        return cls(
            mmsi=str(d["mmsi"]),
            timestamp=_parse_ts(str(d["timestamp"])),
            lat=float(d["lat"]),
            lon=float(d["lon"]),
            name=str(d.get("name", "")),
            sog=None if d.get("sog") is None else float(d["sog"]),
            cog=None if d.get("cog") is None else float(d["cog"]),
        )

    def as_record(self) -> dict[str, Any]:
        r = asdict(self)
        r["timestamp"] = self.timestamp.isoformat().replace("+00:00", "Z")
        return r


def parse_messages(data: Iterable[dict[str, Any]]) -> list[AISMessage]:
    """Parse raw AIS records into validated, time-sorted AISMessage objects."""
    msgs = [AISMessage.from_dict(d) for d in data]
    msgs.sort(key=lambda m: (m.mmsi, m.timestamp))
    return msgs


def load_messages(path: str) -> list[AISMessage]:
    """Load AIS records from a JSON file (list, or {\"messages\": [...]})."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, dict):
        raw = raw.get("messages", raw.get("records", []))
    if not isinstance(raw, list):
        raise ValueError("AIS input must be a JSON list or {'messages': [...]}")
    return parse_messages(raw)


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def _by_vessel(msgs: list[AISMessage]) -> dict[str, list[AISMessage]]:
    tracks: dict[str, list[AISMessage]] = {}
    for m in msgs:
        tracks.setdefault(m.mmsi, []).append(m)
    for track in tracks.values():
        track.sort(key=lambda m: m.timestamp)
    return tracks


def detect_gaps(msgs: list[AISMessage], gap_hours: float = 6.0) -> list[dict[str, Any]]:
    """Find AIS reporting gaps (\"going dark\") longer than gap_hours."""
    findings: list[dict[str, Any]] = []
    for mmsi, track in _by_vessel(msgs).items():
        for a, b in zip(track, track[1:]):
            dt_h = (b.timestamp - a.timestamp).total_seconds() / 3600.0
            if dt_h >= gap_hours:
                dist = haversine_nm(a.lat, a.lon, b.lat, b.lon)
                findings.append({
                    "type": "ais_gap",
                    "mmsi": mmsi,
                    "name": a.name or b.name,
                    "gap_hours": round(dt_h, 2),
                    "distance_nm": round(dist, 2),
                    "dark_from": a.timestamp.isoformat().replace("+00:00", "Z"),
                    "dark_to": b.timestamp.isoformat().replace("+00:00", "Z"),
                    "from": [round(a.lat, 5), round(a.lon, 5)],
                    "to": [round(b.lat, 5), round(b.lon, 5)],
                    "severity": "high" if dt_h >= gap_hours * 2 else "medium",
                })
    return findings


def detect_speed_jumps(
    msgs: list[AISMessage], max_speed_kn: float = 40.0
) -> list[dict[str, Any]]:
    """Find implausible position jumps implying speed > max_speed_kn.

    A vessel teleporting faster than physically possible is a strong
    spoofing / identity-cloning signal.
    """
    findings: list[dict[str, Any]] = []
    for mmsi, track in _by_vessel(msgs).items():
        for a, b in zip(track, track[1:]):
            dt_h = (b.timestamp - a.timestamp).total_seconds() / 3600.0
            if dt_h <= 0:
                continue
            dist = haversine_nm(a.lat, a.lon, b.lat, b.lon)
            implied = dist / dt_h
            if implied > max_speed_kn:
                findings.append({
                    "type": "speed_jump",
                    "mmsi": mmsi,
                    "name": a.name or b.name,
                    "implied_speed_kn": round(implied, 1),
                    "distance_nm": round(dist, 2),
                    "elapsed_hours": round(dt_h, 3),
                    "at": b.timestamp.isoformat().replace("+00:00", "Z"),
                    "from": [round(a.lat, 5), round(a.lon, 5)],
                    "to": [round(b.lat, 5), round(b.lon, 5)],
                    "severity": "high",
                })
    return findings


def detect_loitering(
    msgs: list[AISMessage],
    radius_nm: float = 2.0,
    min_hours: float = 4.0,
) -> list[dict[str, Any]]:
    """Find loitering: a vessel staying within radius_nm for >= min_hours.

    Loitering in open water (away from port) is a classic ship-to-ship
    transfer / rendezvous staging behavior.
    """
    findings: list[dict[str, Any]] = []
    for mmsi, track in _by_vessel(msgs).items():
        i = 0
        n = len(track)
        while i < n:
            anchor = track[i]
            j = i
            while j + 1 < n and haversine_nm(
                anchor.lat, anchor.lon, track[j + 1].lat, track[j + 1].lon
            ) <= radius_nm:
                j += 1
            dur_h = (track[j].timestamp - anchor.timestamp).total_seconds() / 3600.0
            if j > i and dur_h >= min_hours:
                lats = [m.lat for m in track[i:j + 1]]
                lons = [m.lon for m in track[i:j + 1]]
                findings.append({
                    "type": "loitering",
                    "mmsi": mmsi,
                    "name": anchor.name,
                    "duration_hours": round(dur_h, 2),
                    "radius_nm": radius_nm,
                    "reports": j - i + 1,
                    "center": [round(sum(lats) / len(lats), 5),
                               round(sum(lons) / len(lons), 5)],
                    "start": anchor.timestamp.isoformat().replace("+00:00", "Z"),
                    "end": track[j].timestamp.isoformat().replace("+00:00", "Z"),
                    "severity": "medium",
                })
                i = j
            else:
                i += 1
    return findings


def detect_spoofing(msgs: list[AISMessage]) -> list[dict[str, Any]]:
    """Detect spoofing indicators.

    1. Identity conflict: one MMSI broadcasting multiple distinct names.
    2. Static pinning: many reports at the exact same coordinate over time
       (GPS spoof / replay), while claiming to be at sea.
    """
    findings: list[dict[str, Any]] = []
    for mmsi, track in _by_vessel(msgs).items():
        names = {m.name for m in track if m.name}
        if len(names) > 1:
            findings.append({
                "type": "identity_conflict",
                "mmsi": mmsi,
                "names": sorted(names),
                "severity": "high",
            })
        # static pinning: >=3 reports at identical rounded position over >1h
        pins: dict[tuple, list[AISMessage]] = {}
        for m in track:
            pins.setdefault((round(m.lat, 4), round(m.lon, 4)), []).append(m)
        for (plat, plon), group in pins.items():
            if len(group) >= 3:
                span_h = (group[-1].timestamp - group[0].timestamp).total_seconds() / 3600.0
                if span_h >= 1.0:
                    findings.append({
                        "type": "static_pin",
                        "mmsi": mmsi,
                        "name": track[0].name,
                        "position": [plat, plon],
                        "reports": len(group),
                        "span_hours": round(span_h, 2),
                        "severity": "medium",
                    })
    return findings


def detect_rendezvous(
    msgs: list[AISMessage],
    proximity_nm: float = 0.5,
    min_minutes: float = 30.0,
) -> list[dict[str, Any]]:
    """Detect two distinct vessels meeting (within proximity_nm) at sea.

    Sustained close proximity between two MMSIs is the core signature of a
    ship-to-ship transfer used to launder sanctioned cargo.
    """
    findings: list[dict[str, Any]] = []
    tracks = _by_vessel(msgs)
    mmsis = sorted(tracks)
    for ai in range(len(mmsis)):
        for bi in range(ai + 1, len(mmsis)):
            a_track, b_track = tracks[mmsis[ai]], tracks[mmsis[bi]]
            close: list[tuple[datetime, float]] = []
            for a in a_track:
                # nearest b report within 30 min
                best = None
                for b in b_track:
                    if abs((b.timestamp - a.timestamp).total_seconds()) <= 1800:
                        d = haversine_nm(a.lat, a.lon, b.lat, b.lon)
                        if best is None or d < best[1]:
                            best = (a.timestamp, d)
                if best and best[1] <= proximity_nm:
                    close.append(best)
            if len(close) >= 2:
                span_min = (close[-1][0] - close[0][0]).total_seconds() / 60.0
                if span_min >= min_minutes:
                    findings.append({
                        "type": "rendezvous",
                        "vessels": [mmsis[ai], mmsis[bi]],
                        "names": [a_track[0].name, b_track[0].name],
                        "min_distance_nm": round(min(c[1] for c in close), 3),
                        "duration_minutes": round(span_min, 1),
                        "start": close[0][0].isoformat().replace("+00:00", "Z"),
                        "end": close[-1][0].isoformat().replace("+00:00", "Z"),
                        "severity": "high",
                    })
    return findings


def analyze(msgs: list[AISMessage], **kw: Any) -> dict[str, Any]:
    """Run the full detector suite and produce a scored summary report."""
    gaps = detect_gaps(msgs, gap_hours=kw.get("gap_hours", 6.0))
    jumps = detect_speed_jumps(msgs, max_speed_kn=kw.get("max_speed_kn", 40.0))
    loiter = detect_loitering(
        msgs,
        radius_nm=kw.get("loiter_radius_nm", 2.0),
        min_hours=kw.get("loiter_min_hours", 4.0),
    )
    spoof = detect_spoofing(msgs)
    rdv = detect_rendezvous(
        msgs,
        proximity_nm=kw.get("rendezvous_nm", 0.5),
        min_minutes=kw.get("rendezvous_min_minutes", 30.0),
    )
    findings = gaps + jumps + loiter + spoof + rdv

    weights = {"high": 3, "medium": 2, "low": 1}
    per_vessel: dict[str, int] = {}
    for f in findings:
        score = weights.get(f.get("severity", "low"), 1)
        for key in ("mmsi",):
            if key in f:
                per_vessel[f[key]] = per_vessel.get(f[key], 0) + score
        for v in f.get("vessels", []):
            per_vessel[v] = per_vessel.get(v, 0) + score

    vessels = sorted(per_vessel.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "tool": "maritimeint",
        "vessels_tracked": len(_by_vessel(msgs)),
        "messages": len(msgs),
        "finding_counts": {
            "ais_gap": len(gaps),
            "speed_jump": len(jumps),
            "loitering": len(loiter),
            "spoofing": len(spoof),
            "rendezvous": len(rdv),
        },
        "risk_ranking": [{"mmsi": m, "risk_score": s} for m, s in vessels],
        "findings": findings,
    }
