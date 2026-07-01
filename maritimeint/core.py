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

import csv
import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

EARTH_RADIUS_NM = 3440.065  # nautical miles


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Raises a clear :class:`ValueError` (naming the offending value) rather than
    the bare ``fromisoformat`` message, so a malformed AIS timestamp is
    actionable instead of cryptic.
    """
    s = value.strip()
    if not s:
        raise ValueError("empty timestamp")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(
            f"invalid ISO-8601 timestamp {value!r}: {exc}"
        ) from exc
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
        if not isinstance(d, dict):
            raise ValueError(
                f"AIS record must be an object/dict, got {type(d).__name__}"
            )
        if "mmsi" not in d:
            raise ValueError("AIS record missing 'mmsi'")
        for key in ("timestamp", "lat", "lon"):
            if key not in d:
                raise ValueError(f"AIS record for {d.get('mmsi')} missing '{key}'")
        mmsi = str(d["mmsi"])

        def _num(field: str, val: Any) -> float:
            try:
                return float(val)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"AIS record for {mmsi} has non-numeric {field}={val!r}"
                ) from exc

        lat = _num("lat", d["lat"])
        lon = _num("lon", d["lon"])
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"AIS record for {mmsi} has out-of-range lat={lat}")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"AIS record for {mmsi} has out-of-range lon={lon}")
        return cls(
            mmsi=mmsi,
            timestamp=_parse_ts(str(d["timestamp"])),
            lat=lat,
            lon=lon,
            name=str(d.get("name", "")),
            sog=None if d.get("sog") is None else _num("sog", d["sog"]),
            cog=None if d.get("cog") is None else _num("cog", d["cog"]),
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
    """Load AIS records from JSON (list / {"messages": [...]}) or CSV.

    CSV is the common real-world format from AIS providers; a header row with
    mmsi/timestamp/lat/lon (and optional name/sog/cog/imo) is expected. Empty cells
    are treated as absent so optional fields don't choke.
    """
    if path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8", newline="") as fh:
            rows = []
            for row in csv.DictReader(fh):
                rows.append({k: v for k, v in row.items() if v not in ("", None)})
        return parse_messages(rows)
    with open(path, "r", encoding="utf-8") as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: not valid JSON ({exc})") from exc
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


def detect_dark_rendezvous(
    msgs: list[AISMessage],
    gap_hours: float = 6.0,
    proximity_nm: float = 5.0,
) -> list[dict[str, Any]]:
    """Correlate one vessel going dark with another loitering at the spot.

    The real sanctions-evasion STS signature: a tanker switches off AIS, and a
    lightering vessel sits near where it vanished / reappears. `detect_rendezvous`
    needs *both* parties broadcasting; this catches the case where one stops.

    For each AIS gap in vessel A, find vessels B still reporting *inside A's dark
    window* and *near A's last-seen or first-seen position*.
    """
    findings: list[dict[str, Any]] = []
    gaps = detect_gaps(msgs, gap_hours=gap_hours)
    tracks = _by_vessel(msgs)
    for g in gaps:
        a_mmsi = g["mmsi"]
        t0 = _parse_ts(g["dark_from"])
        t1 = _parse_ts(g["dark_to"])
        endpoints = [tuple(g["from"]), tuple(g["to"])]
        for b_mmsi, b_track in tracks.items():
            if b_mmsi == a_mmsi:
                continue
            best: tuple[float, datetime] | None = None
            count = 0
            for m in b_track:
                if not (t0 <= m.timestamp <= t1):
                    continue
                d = min(haversine_nm(m.lat, m.lon, p[0], p[1]) for p in endpoints)
                if d <= proximity_nm:
                    count += 1
                    if best is None or d < best[0]:
                        best = (d, m.timestamp)
            if best and count >= 1:
                findings.append({
                    "type": "dark_rendezvous",
                    "vessels": [a_mmsi, b_mmsi],
                    "dark_vessel": a_mmsi,
                    "present_vessel": b_mmsi,
                    "names": [g.get("name", ""), b_track[0].name],
                    "min_distance_nm": round(best[0], 2),
                    "present_reports": count,
                    "gap_hours": g["gap_hours"],
                    "dark_from": g["dark_from"],
                    "dark_to": g["dark_to"],
                    "at": best[1].isoformat().replace("+00:00", "Z"),
                    "severity": "high",
                })
    return findings


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, in degrees [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def detect_gps_anomalies(
    msgs: list[AISMessage],
    circle_radius_nm: float = 3.0,
    min_circle_points: int = 8,
    jam_window_minutes: float = 30.0,
    jam_min_vessels: int = 3,
    jam_round: int = 3,
) -> list[dict[str, Any]]:
    """Detect GPS spoofing / jamming artifacts.

    1. **circle_spoof** — a single track tracing >= 360 deg of cumulative turning
       while confined to a small radius (the "ships circling an airport" artifact
       seen under GPS spoofing near conflict zones).
    2. **gps_jamming** — many *distinct* vessels reporting the near-identical
       position within a short time window (a jamming hotspot snaps everyone to
       one synthetic point).
    """
    findings: list[dict[str, Any]] = []

    # 1. per-vessel circular drift, measured as angular coverage around the
    #    track centroid: a spoofed "circling" track populates the whole compass
    #    around its center, while a straight passage clusters into two opposite
    #    bearings (a large angular gap). Robust to sampling density.
    for mmsi, track in _by_vessel(msgs).items():
        if len(track) < min_circle_points:
            continue
        clat = sum(m.lat for m in track) / len(track)
        clon = sum(m.lon for m in track) / len(track)
        max_r = max(haversine_nm(clat, clon, m.lat, m.lon) for m in track)
        if max_r > circle_radius_nm or max_r < 1e-3:
            continue
        angles = sorted(_bearing(clat, clon, m.lat, m.lon) for m in track
                        if haversine_nm(clat, clon, m.lat, m.lon) > 1e-4)
        if len(angles) < min_circle_points:
            continue
        gaps = [b - a for a, b in zip(angles, angles[1:])]
        gaps.append(360.0 - angles[-1] + angles[0])  # wrap-around gap
        coverage = 360.0 - max(gaps)
        if coverage >= 300.0:
            findings.append({
                "type": "circle_spoof",
                "mmsi": mmsi,
                "name": track[0].name,
                "arc_degrees": round(coverage, 1),
                "radius_nm": round(max_r, 2),
                "reports": len(track),
                "center": [round(clat, 5), round(clon, 5)],
                "start": track[0].timestamp.isoformat().replace("+00:00", "Z"),
                "end": track[-1].timestamp.isoformat().replace("+00:00", "Z"),
                "severity": "high",
            })

    # 2. cross-vessel jamming hotspots
    buckets: dict[tuple, dict[str, AISMessage]] = {}
    win = jam_window_minutes * 60.0
    for m in msgs:
        tb = int(m.timestamp.timestamp() // win)
        key = (round(m.lat, jam_round), round(m.lon, jam_round), tb)
        buckets.setdefault(key, {})[m.mmsi] = m
    seen: set[tuple] = set()
    for (plat, plon, _tb), group in buckets.items():
        if len(group) >= jam_min_vessels:
            sig = (plat, plon)
            if sig in seen:
                continue
            seen.add(sig)
            ts = sorted(m.timestamp for m in group.values())
            findings.append({
                "type": "gps_jamming",
                "position": [plat, plon],
                "vessels": sorted(group),
                "vessel_count": len(group),
                "window_start": ts[0].isoformat().replace("+00:00", "Z"),
                "window_end": ts[-1].isoformat().replace("+00:00", "Z"),
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
    dark_rdv = detect_dark_rendezvous(
        msgs,
        gap_hours=kw.get("gap_hours", 6.0),
        proximity_nm=kw.get("dark_rendezvous_nm", 5.0),
    )
    gps = detect_gps_anomalies(msgs)

    # track-interaction & behaviour layer (encounters module)
    from .encounters import (
        detect_close_quarters,
        detect_shadowing,
        detect_convoy,
        detect_drift,
    )
    cq = detect_close_quarters(
        msgs,
        cpa_nm=kw.get("cpa_nm", 0.5),
        tcpa_max_minutes=kw.get("tcpa_max_minutes", 30.0),
    )
    shadow = detect_shadowing(
        msgs,
        standoff_max_nm=kw.get("standoff_max_nm", 8.0),
        min_minutes=kw.get("shadow_min_minutes", 90.0),
    )
    convoy = detect_convoy(
        msgs,
        cluster_nm=kw.get("cluster_nm", 3.0),
        min_vessels=kw.get("convoy_min_vessels", 3),
    )
    drift = detect_drift(
        msgs,
        max_sog_kn=kw.get("drift_max_sog_kn", 1.5),
        min_minutes=kw.get("drift_min_minutes", 60.0),
    )

    findings = (gaps + jumps + loiter + spoof + rdv + dark_rdv + gps
                + cq + shadow + convoy + drift)

    # optional spatial enrichment: tag every finding with the zones it falls in
    zones = kw.get("zones")
    if zones:
        from .zones import annotate_findings
        annotate_findings(findings, zones)

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
            "dark_rendezvous": len(dark_rdv),
            "gps_anomaly": len(gps),
            "close_quarters": len(cq),
            "shadowing": len(shadow),
            "convoy": len(convoy),
            "drift": len(drift),
        },
        "risk_ranking": [{"mmsi": m, "risk_score": s} for m, s in vessels],
        "findings": findings,
    }
