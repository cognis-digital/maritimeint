"""Pattern-of-life & multi-signal correlation for MARITIMEINT.

The single-signal detectors in :mod:`maritimeint.core` each answer one question
("did this vessel go dark?", "did it loiter?"). This module *correlates* those
signals over time into the composite pictures an analyst actually reasons about:

* **gap_timeline** — reconstruct each vessel's "going dark" history as an ordered
  timeline of dark windows with the reappearance displacement, so a reviewer sees
  the *pattern* of disappearances (routine sensor dropout vs. deliberate, repeated,
  long dark legs) rather than isolated gap findings.
* **sts_transfer_score** — the ship-to-ship transfer signature is rarely one clean
  event; it is a *stack*: a vessel loiters, another goes dark near it, they sit in
  proximity. This fuses loitering + (dark_)rendezvous + gaps that overlap in time
  and space into a single scored, explained STS-candidate event.
* **pattern_of_life** — a per-vessel behavioural baseline: active hours, area of
  operation (bounding box + centroid), typical speed, and the fraction of time spent
  loitering / dark. The routine a vessel keeps; deviations are what merit a look.

Pure standard library; findings serialise through the existing exporters. This is
descriptive maritime-domain awareness and compliance triage, not targeting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .core import (
    AISMessage,
    _by_vessel,
    haversine_nm,
    detect_gaps,
    detect_loitering,
    detect_rendezvous,
    detect_dark_rendezvous,
    _parse_ts,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# gap timeline
# --------------------------------------------------------------------------- #
def gap_timeline(
    msgs: list[AISMessage],
    gap_hours: float = 6.0,
) -> list[dict[str, Any]]:
    """Per vessel, order its AIS dark windows into a timeline with summary stats.

    Returns one record per vessel that has >= 1 gap, carrying the ordered list of
    dark windows (each with hours, reappearance displacement, and a rough
    reappearance drift speed) plus roll-ups: how many times it went dark, total dark
    hours, longest dark window. A vessel that repeatedly goes dark for long stretches
    and reappears far away is a very different risk from one with a single short
    sensor dropout — the timeline makes that legible.
    """
    gaps = detect_gaps(msgs, gap_hours=gap_hours)
    per: dict[str, list[dict[str, Any]]] = {}
    for g in gaps:
        per.setdefault(g["mmsi"], []).append(g)
    out: list[dict[str, Any]] = []
    tracks = _by_vessel(msgs)
    for mmsi, glist in per.items():
        glist.sort(key=lambda g: g["dark_from"])
        windows = []
        for g in glist:
            drift = (round(g["distance_nm"] / g["gap_hours"], 2)
                     if g["gap_hours"] else 0.0)
            windows.append({
                "dark_from": g["dark_from"],
                "dark_to": g["dark_to"],
                "gap_hours": g["gap_hours"],
                "displacement_nm": g["distance_nm"],
                "reappear_drift_kn": drift,
                "from": g["from"],
                "to": g["to"],
            })
        total_dark = round(sum(w["gap_hours"] for w in windows), 2)
        longest = max(w["gap_hours"] for w in windows)
        name = tracks.get(mmsi, [None])[0].name if tracks.get(mmsi) else glist[0].get("name", "")
        out.append({
            "type": "gap_timeline",
            "mmsi": mmsi,
            "name": name,
            "dark_events": len(windows),
            "total_dark_hours": total_dark,
            "longest_dark_hours": longest,
            "windows": windows,
            "severity": "high" if (len(windows) >= 3 or longest >= gap_hours * 3)
            else "medium",
        })
    out.sort(key=lambda r: (r["dark_events"], r["total_dark_hours"]), reverse=True)
    return out


# --------------------------------------------------------------------------- #
# STS transfer scoring — fuse loiter + rendezvous + gap
# --------------------------------------------------------------------------- #
def _overlaps(t0: datetime, t1: datetime, u0: datetime, u1: datetime) -> bool:
    return t0 <= u1 and u0 <= t1


def sts_transfer_score(
    msgs: list[AISMessage],
    loiter_radius_nm: float = 2.0,
    loiter_min_hours: float = 3.0,
    rendezvous_nm: float = 0.5,
    proximity_nm: float = 5.0,
    gap_hours: float = 6.0,
) -> list[dict[str, Any]]:
    """Fuse loitering + rendezvous/dark-rendezvous + gaps into scored STS candidates.

    Each ``rendezvous`` / ``dark_rendezvous`` between two vessels is the anchor. We
    then look for corroborating context near that meeting in time: did either vessel
    loiter around then? Did either go dark? Each corroborating signal adds to a score
    and an evidence list, turning a bare proximity event into an explained
    ship-to-ship-transfer candidate an analyst can triage.
    """
    rdv = detect_rendezvous(msgs, proximity_nm=rendezvous_nm)
    drdv = detect_dark_rendezvous(msgs, gap_hours=gap_hours, proximity_nm=proximity_nm)
    loiter = detect_loitering(msgs, radius_nm=loiter_radius_nm, min_hours=loiter_min_hours)
    gaps = detect_gaps(msgs, gap_hours=gap_hours)

    def _span(f: dict[str, Any], a="start", b="end") -> tuple[datetime, datetime]:
        return _parse_ts(f[a]), _parse_ts(f[b])

    loiter_by_v: dict[str, list[dict[str, Any]]] = {}
    for f in loiter:
        loiter_by_v.setdefault(f["mmsi"], []).append(f)
    gap_by_v: dict[str, list[dict[str, Any]]] = {}
    for f in gaps:
        gap_by_v.setdefault(f["mmsi"], []).append(f)

    out: list[dict[str, Any]] = []
    for anchor in rdv + drdv:
        vessels = anchor.get("vessels", [])
        is_dark = anchor["type"] == "dark_rendezvous"
        a0 = _parse_ts(anchor.get("start", anchor.get("dark_from")))
        a1 = _parse_ts(anchor.get("end", anchor.get("dark_to")))
        score = 3 if is_dark else 2  # a dark meeting is a stronger base signal
        evidence = [f"{anchor['type']} between {' & '.join(vessels)}"]
        for v in vessels:
            for lf in loiter_by_v.get(v, []):
                if _overlaps(a0, a1, _parse_ts(lf["start"]), _parse_ts(lf["end"])):
                    score += 2
                    evidence.append(f"{v} loitered {lf['duration_hours']}h nearby")
                    break
            for gf in gap_by_v.get(v, []):
                if _overlaps(a0, a1, _parse_ts(gf["dark_from"]), _parse_ts(gf["dark_to"])):
                    score += 2
                    evidence.append(f"{v} went dark {gf['gap_hours']}h during the window")
                    break
        out.append({
            "type": "sts_candidate",
            "vessels": vessels,
            "names": anchor.get("names", []),
            "anchor": anchor["type"],
            "min_distance_nm": anchor.get("min_distance_nm"),
            "start": _iso(a0),
            "end": _iso(a1),
            "score": score,
            "evidence": evidence,
            "severity": "high" if score >= 5 else "medium",
        })
    out.sort(key=lambda f: f["score"], reverse=True)
    return out


# --------------------------------------------------------------------------- #
# pattern of life — per-vessel behavioural baseline
# --------------------------------------------------------------------------- #
def pattern_of_life(
    msgs: list[AISMessage],
    gap_hours: float = 6.0,
    loiter_radius_nm: float = 2.0,
    loiter_min_hours: float = 3.0,
) -> list[dict[str, Any]]:
    """Summarise each vessel's routine: where, when, how fast, how often dark/loiter.

    For every vessel: reporting span, active hours-of-day histogram, area of
    operation (bounding box + centroid + max extent), speed statistics, and the count
    of dark and loitering events over the window. This is the baseline against which
    a deviation ("it never usually goes to that EEZ / never usually goes dark") stands
    out — the routine an analyst learns before an anomaly means anything.
    """
    tracks = _by_vessel(msgs)
    gap_ct: dict[str, int] = {}
    for g in detect_gaps(msgs, gap_hours=gap_hours):
        gap_ct[g["mmsi"]] = gap_ct.get(g["mmsi"], 0) + 1
    loiter_ct: dict[str, int] = {}
    for lf in detect_loitering(msgs, radius_nm=loiter_radius_nm, min_hours=loiter_min_hours):
        loiter_ct[lf["mmsi"]] = loiter_ct.get(lf["mmsi"], 0) + 1

    out: list[dict[str, Any]] = []
    for mmsi, track in tracks.items():
        lats = [m.lat for m in track]
        lons = [m.lon for m in track]
        clat, clon = sum(lats) / len(lats), sum(lons) / len(lons)
        extent = max((haversine_nm(clat, clon, m.lat, m.lon) for m in track), default=0.0)
        span_h = ((track[-1].timestamp - track[0].timestamp).total_seconds() / 3600.0
                  if len(track) > 1 else 0.0)
        hours = [0] * 24
        for m in track:
            hours[m.timestamp.hour] += 1
        active_hours = sorted(h for h in range(24) if hours[h])
        sogs = [m.sog for m in track if m.sog is not None]
        moving = [s for s in sogs if s is not None and s > 0.5]
        name = next((m.name for m in track if m.name), "")
        out.append({
            "type": "pattern_of_life",
            "mmsi": mmsi,
            "name": name,
            "flag_hint": mmsi[:3] if mmsi[:3].isdigit() else "",
            "reports": len(track),
            "span_hours": round(span_h, 2),
            "first_seen": _iso(track[0].timestamp),
            "last_seen": _iso(track[-1].timestamp),
            "active_hours_utc": active_hours,
            "bbox": [round(min(lats), 5), round(min(lons), 5),
                     round(max(lats), 5), round(max(lons), 5)],
            "centroid": [round(clat, 5), round(clon, 5)],
            "area_extent_nm": round(extent, 2),
            "mean_sog_kn": round(sum(moving) / len(moving), 2) if moving else 0.0,
            "max_sog_kn": round(max(sogs), 2) if sogs else 0.0,
            "dark_events": gap_ct.get(mmsi, 0),
            "loiter_events": loiter_ct.get(mmsi, 0),
            "severity": "low",
        })
    out.sort(key=lambda r: (r["dark_events"] + r["loiter_events"], r["reports"]),
             reverse=True)
    return out


def analyze_patterns(msgs: list[AISMessage], **kw: Any) -> dict[str, Any]:
    """Run the pattern-of-life / correlation layer; mirrors the analyze() shape."""
    timeline = gap_timeline(msgs, gap_hours=kw.get("gap_hours", 6.0))
    sts = sts_transfer_score(
        msgs,
        loiter_radius_nm=kw.get("loiter_radius_nm", 2.0),
        loiter_min_hours=kw.get("loiter_min_hours", 3.0),
        rendezvous_nm=kw.get("rendezvous_nm", 0.5),
        proximity_nm=kw.get("dark_rendezvous_nm", 5.0),
        gap_hours=kw.get("gap_hours", 6.0),
    )
    pol = pattern_of_life(
        msgs,
        gap_hours=kw.get("gap_hours", 6.0),
        loiter_radius_nm=kw.get("loiter_radius_nm", 2.0),
        loiter_min_hours=kw.get("loiter_min_hours", 3.0),
    )
    findings = timeline + sts + pol
    zones = kw.get("zones")
    if zones:
        from .zones import annotate_findings
        annotate_findings(findings, zones)
    return {
        "tool": "maritimeint",
        "mode": "patterns",
        "vessels_tracked": len(_by_vessel(msgs)),
        "messages": len(msgs),
        "finding_counts": {
            "gap_timeline": len(timeline),
            "sts_candidate": len(sts),
            "pattern_of_life": len(pol),
        },
        "findings": findings,
    }
