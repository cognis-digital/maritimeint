"""Track-interaction & vessel-behaviour intelligence for MARITIMEINT.

Where :mod:`maritimeint.core` scores each vessel mostly in isolation (gaps, speed
jumps, loitering, single-vessel spoofing), this module reasons about *how tracks
relate to one another and how a single track behaves over time*. Pure standard
library; every detector returns plain dicts that serialise straight to JSON and
flow through the existing :mod:`maritimeint.intel` exporters and the ``analyze``
risk ranking.

Detectors
---------
* **close_quarters** (CPA / TCPA) — Closest Point of Approach distance and Time
  to CPA between every pair of vessels, the canonical collision-avoidance and
  force-protection standoff primitive. Flags converging tracks projected to pass
  within a danger radius. Defensive / safety / early-warning only — this computes
  *separation*, never an intercept or any maneuvering instruction.
* **shadowing** — one vessel persistently trailing another at a roughly constant
  standoff distance on a matched course over an extended period. Distinct from a
  rendezvous (no closing to contact): a documented surveillance / interdiction /
  escort-precursor signature.
* **convoy** — a cluster of vessels moving together (tight spatial grouping plus
  matched heading and speed) sustained across multiple reports: coordinated
  grey-fleet flotillas, escort groups, or shepherded transfers.
* **drift** — a vessel barely making way (very low SOG) while its position keeps
  changing in an unpowered way (set & drift by current/wind, erratic heading).
  A not-under-command / disabled / possible-distress safety signal.

Threat / defensive framing
---------------------------
None of this is targeting. CPA/TCPA is the same math a bridge watch-officer's
collision-avoidance radar runs; here it is applied retrospectively to AIS history
for situational awareness and force protection (e.g. *did an unknown contact close
inside our standoff perimeter?*). Shadowing and convoy detection surface
coordination that single-vessel anomaly detection misses. Drift flags vessels that
may need assistance or that have lost propulsion in a traffic lane.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .core import AISMessage, haversine_nm, _by_vessel, _bearing


# --------------------------------------------------------------------------- #
# small geo helpers
# --------------------------------------------------------------------------- #
def _angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, in [0, 180]."""
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _local_xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Equirectangular projection (nm) around a local origin.

    Good for the short ranges (a few nm) and short time windows CPA cares about;
    avoids great-circle trig inside the inner pairwise loop.
    """
    x = (lon - lon0) * 60.0 * math.cos(math.radians(lat0))  # nm east
    y = (lat - lat0) * 60.0                                   # nm north
    return x, y


def _interp(track: list[AISMessage], t: datetime) -> tuple[float, float] | None:
    """Linear-interpolate a vessel's position at time ``t`` (None if out of range)."""
    if not track or t < track[0].timestamp or t > track[-1].timestamp:
        return None
    for a, b in zip(track, track[1:]):
        if a.timestamp <= t <= b.timestamp:
            span = (b.timestamp - a.timestamp).total_seconds()
            if span <= 0:
                return a.lat, a.lon
            f = (t - a.timestamp).total_seconds() / span
            return a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f
    return None


def _track_speed_course(track: list[AISMessage], idx: int) -> tuple[float, float]:
    """Best-estimate (sog_kn, cog_deg) at sample ``idx`` using reported values
    when present, else derived from the neighbouring fixes."""
    m = track[idx]
    sog = m.sog
    cog = m.cog
    if sog is not None and cog is not None:
        return sog, cog
    # derive from the segment ending at idx (or starting, for the first point)
    if idx == 0 and len(track) > 1:
        a, b = track[0], track[1]
    elif idx > 0:
        a, b = track[idx - 1], track[idx]
    else:
        return sog or 0.0, cog or 0.0
    dt_h = (b.timestamp - a.timestamp).total_seconds() / 3600.0
    if dt_h <= 0:
        return sog or 0.0, cog or 0.0
    dist = haversine_nm(a.lat, a.lon, b.lat, b.lon)
    d_sog = dist / dt_h
    d_cog = _bearing(a.lat, a.lon, b.lat, b.lon)
    return (sog if sog is not None else d_sog,
            cog if cog is not None else d_cog)


# --------------------------------------------------------------------------- #
# CPA / TCPA — closest point of approach between vessel pairs
# --------------------------------------------------------------------------- #
def _pair_cpa(
    a: AISMessage, av: tuple[float, float],
    b: AISMessage, bv: tuple[float, float],
) -> tuple[float, float, float]:
    """CPA distance (nm), TCPA (minutes from the common time), current range (nm).

    Treats each vessel as moving in a straight line at its instantaneous velocity
    (the standard relative-motion CPA model). ``av``/``bv`` are (sog_kn, cog_deg).
    """
    ax, ay = _local_xy(a.lat, a.lon, a.lat, a.lon)  # a at origin
    bx, by = _local_xy(b.lat, b.lon, a.lat, a.lon)

    def _vel(sog: float, cog: float) -> tuple[float, float]:
        r = math.radians(cog)
        return sog * math.sin(r), sog * math.cos(r)  # (east, north) nm/h

    avx, avy = _vel(*av)
    bvx, bvy = _vel(*bv)
    # relative position and velocity of b w.r.t. a
    rx, ry = bx - ax, by - ay
    rvx, rvy = bvx - avx, bvy - avy
    rng_now = math.hypot(rx, ry)
    rv2 = rvx * rvx + rvy * rvy
    if rv2 < 1e-9:  # parallel / stationary relative motion
        return rng_now, 0.0, rng_now
    tcpa_h = -(rx * rvx + ry * rvy) / rv2
    if tcpa_h < 0:  # CPA already passed; closest is now
        return rng_now, 0.0, rng_now
    cx = rx + rvx * tcpa_h
    cy = ry + rvy * tcpa_h
    return math.hypot(cx, cy), tcpa_h * 60.0, rng_now


def detect_close_quarters(
    msgs: list[AISMessage],
    cpa_nm: float = 0.5,
    tcpa_max_minutes: float = 30.0,
    max_pair_dt_minutes: float = 15.0,
) -> list[dict[str, Any]]:
    """Flag vessel pairs projected to pass within ``cpa_nm`` within ``tcpa_max``.

    For every pair, at each time their reports are within ``max_pair_dt`` of one
    another, compute CPA/TCPA from their instantaneous velocities. The worst
    (smallest) CPA across the encounter is reported. A small CPA with a short,
    positive TCPA is a converging close-quarters situation — collision risk for
    safety, perimeter breach for force protection.
    """
    findings: list[dict[str, Any]] = []
    tracks = _by_vessel(msgs)
    mmsis = sorted(tracks)
    pair_dt = max_pair_dt_minutes * 60.0
    for i in range(len(mmsis)):
        for j in range(i + 1, len(mmsis)):
            ta, tb = tracks[mmsis[i]], tracks[mmsis[j]]
            best: dict[str, Any] | None = None
            for ia, a in enumerate(ta):
                # nearest-in-time b report
                cand = min(
                    ((abs((b.timestamp - a.timestamp).total_seconds()), ib, b)
                     for ib, b in enumerate(tb)),
                    default=None,
                )
                if cand is None or cand[0] > pair_dt:
                    continue
                _, ib, b = cand
                av = _track_speed_course(ta, ia)
                bv = _track_speed_course(tb, ib)
                cpa, tcpa, rng = _pair_cpa(a, av, b, bv)
                if cpa <= cpa_nm and 0.0 <= tcpa <= tcpa_max_minutes:
                    if best is None or cpa < best["cpa_nm"]:
                        best = {
                            "type": "close_quarters",
                            "vessels": [mmsis[i], mmsis[j]],
                            "names": [ta[0].name, tb[0].name],
                            "cpa_nm": round(cpa, 3),
                            "tcpa_minutes": round(tcpa, 1),
                            "range_at_detection_nm": round(rng, 3),
                            "at": a.timestamp.isoformat().replace("+00:00", "Z"),
                            "from": [round(a.lat, 5), round(a.lon, 5)],
                            "severity": "high" if cpa <= cpa_nm / 2 else "medium",
                        }
            if best:
                findings.append(best)
    return findings


# --------------------------------------------------------------------------- #
# shadowing — persistent trailing at standoff
# --------------------------------------------------------------------------- #
def detect_shadowing(
    msgs: list[AISMessage],
    standoff_min_nm: float = 0.3,
    standoff_max_nm: float = 8.0,
    course_tol_deg: float = 25.0,
    min_minutes: float = 90.0,
    min_overlaps: int = 4,
    max_pair_dt_minutes: float = 20.0,
) -> list[dict[str, Any]]:
    """Detect one vessel persistently trailing another at a held standoff.

    Signature: across an extended window the two tracks keep a separation inside
    ``[standoff_min, standoff_max]`` nm (close, but *not* closing to contact like a
    rendezvous) while their courses stay matched within ``course_tol`` and the
    follower sits *behind* the leader along the leader's course. Distinct from
    ``rendezvous`` (which converges) and ``convoy`` (which is a tight cluster of
    several abreast). Surveillance / interdiction / escort-precursor signature.
    """
    findings: list[dict[str, Any]] = []
    tracks = _by_vessel(msgs)
    mmsis = sorted(tracks)
    pair_dt = max_pair_dt_minutes * 60.0
    for i in range(len(mmsis)):
        for j in range(i + 1, len(mmsis)):
            ta, tb = tracks[mmsis[i]], tracks[mmsis[j]]
            overlaps: list[tuple[datetime, float, float, str]] = []
            for ia, a in enumerate(ta):
                cand = min(
                    ((abs((b.timestamp - a.timestamp).total_seconds()), ib, b)
                     for ib, b in enumerate(tb)),
                    default=None,
                )
                if cand is None or cand[0] > pair_dt:
                    continue
                _, ib, b = cand
                d = haversine_nm(a.lat, a.lon, b.lat, b.lon)
                if not (standoff_min_nm <= d <= standoff_max_nm):
                    continue
                _, acog = _track_speed_course(ta, ia)
                _, bcog = _track_speed_course(tb, ib)
                if _angle_diff(acog, bcog) > course_tol_deg:
                    continue
                # who is following whom: the trailer is the one *behind* the
                # other along the shared course. bearing from leader to follower
                # should oppose the course of travel.
                brg_a_to_b = _bearing(a.lat, a.lon, b.lat, b.lon)
                # if b is behind a (bearing a->b ~ reciprocal of a's course), a leads
                a_leads = _angle_diff(brg_a_to_b, (acog + 180.0) % 360.0) <= 90.0
                leader, follower = (mmsis[i], mmsis[j]) if a_leads else (mmsis[j], mmsis[i])
                overlaps.append((a.timestamp, d, (acog + bcog) / 2.0, leader))
            if len(overlaps) >= min_overlaps:
                span_min = (overlaps[-1][0] - overlaps[0][0]).total_seconds() / 60.0
                if span_min >= min_minutes:
                    # majority vote on leader for a stable label
                    leaders = [o[3] for o in overlaps]
                    leader = max(set(leaders), key=leaders.count)
                    follower = mmsis[j] if leader == mmsis[i] else mmsis[i]
                    dists = [o[1] for o in overlaps]
                    findings.append({
                        "type": "shadowing",
                        "vessels": [mmsis[i], mmsis[j]],
                        "leader": leader,
                        "follower": follower,
                        "names": {mmsis[i]: ta[0].name, mmsis[j]: tb[0].name},
                        "mean_standoff_nm": round(sum(dists) / len(dists), 2),
                        "min_standoff_nm": round(min(dists), 2),
                        "max_standoff_nm": round(max(dists), 2),
                        "duration_minutes": round(span_min, 1),
                        "overlaps": len(overlaps),
                        "start": overlaps[0][0].isoformat().replace("+00:00", "Z"),
                        "end": overlaps[-1][0].isoformat().replace("+00:00", "Z"),
                        "severity": "high" if span_min >= min_minutes * 2 else "medium",
                    })
    return findings


# --------------------------------------------------------------------------- #
# convoy / co-movement clustering
# --------------------------------------------------------------------------- #
def detect_convoy(
    msgs: list[AISMessage],
    cluster_nm: float = 3.0,
    course_tol_deg: float = 20.0,
    speed_tol_kn: float = 4.0,
    min_vessels: int = 3,
    min_epochs: int = 3,
    epoch_minutes: float = 30.0,
) -> list[dict[str, Any]]:
    """Detect groups of vessels moving together as a coordinated formation.

    At each time epoch, single-link cluster the vessels present by proximity
    (``cluster_nm``), then keep clusters whose members also share heading
    (within ``course_tol``) and speed (within ``speed_tol``) and number at least
    ``min_vessels``. A set of vessels that forms such a cluster across
    ``min_epochs`` separate epochs is reported as a convoy. Surfaces escort
    groups and shepherded grey-fleet flotillas that per-vessel anomaly detection
    treats as unrelated tracks.
    """
    tracks = _by_vessel(msgs)
    if len(tracks) < min_vessels:
        return []
    # epoch buckets keyed by floor(time / epoch)
    win = epoch_minutes * 60.0
    epochs: dict[int, list[tuple[str, AISMessage, float, float]]] = {}
    for mmsi, track in tracks.items():
        for idx, m in enumerate(track):
            sog, cog = _track_speed_course(track, idx)
            tb = int(m.timestamp.timestamp() // win)
            epochs.setdefault(tb, []).append((mmsi, m, sog, cog))

    # group membership signature -> list of epoch buckets it appeared in
    groups: dict[frozenset, list[int]] = {}
    for tb, members in epochs.items():
        # one report per vessel per epoch (first wins)
        seen: dict[str, tuple[AISMessage, float, float]] = {}
        for mmsi, m, sog, cog in members:
            seen.setdefault(mmsi, (m, sog, cog))
        items = list(seen.items())
        n = len(items)
        if n < min_vessels:
            continue
        # single-link clustering by proximity
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for x in range(n):
            for y in range(x + 1, n):
                (mx, sx, cx) = items[x][1]
                (my, sy, cy) = items[y][1]
                if (haversine_nm(mx.lat, mx.lon, my.lat, my.lon) <= cluster_nm
                        and _angle_diff(cx, cy) <= course_tol_deg
                        and abs(sx - sy) <= speed_tol_kn):
                    parent[find(x)] = find(y)
        clusters: dict[int, list[int]] = {}
        for x in range(n):
            clusters.setdefault(find(x), []).append(x)
        for idxs in clusters.values():
            if len(idxs) >= min_vessels:
                sig = frozenset(items[k][0] for k in idxs)
                groups.setdefault(sig, []).append(tb)

    findings: list[dict[str, Any]] = []
    for sig, tbs in groups.items():
        if len(set(tbs)) >= min_epochs:
            members = sorted(sig)
            ts = sorted(set(tbs))

            def _iso(epoch_idx: int) -> str:
                dt = datetime.fromtimestamp(epoch_idx * win, tz=timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")

            findings.append({
                "type": "convoy",
                "vessels": members,
                "names": {m: tracks[m][0].name for m in members},
                "vessel_count": len(members),
                "epochs": len(ts),
                "start": _iso(ts[0]),
                "end": _iso(ts[-1] + 1),
                "severity": "medium",
            })
    return findings


# --------------------------------------------------------------------------- #
# drift — not-under-command / disabled / distress
# --------------------------------------------------------------------------- #
def detect_drift(
    msgs: list[AISMessage],
    max_sog_kn: float = 1.5,
    min_heading_change_deg: float = 60.0,
    min_minutes: float = 60.0,
    min_reports: int = 3,
) -> list[dict[str, Any]]:
    """Detect a vessel adrift: barely making way yet changing heading erratically.

    A powered vessel holding station keeps a steady heading; a vessel *adrift*
    (lost propulsion, anchor dragging, not-under-command) creeps along at near-zero
    SOG while its heading swings with the set of the current/wind. We require a run
    of consecutive low-SOG fixes spanning ``min_minutes`` over which the heading
    between fixes varies by at least ``min_heading_change_deg``. A safety /
    possible-distress early-warning signal, not an anomaly-of-intent.
    """
    findings: list[dict[str, Any]] = []
    for mmsi, track in _by_vessel(msgs).items():
        i, n = 0, len(track)
        while i < n - 1:
            run = [track[i]]
            j = i
            while j + 1 < n:
                sog, _ = _track_speed_course(track, j + 1)
                if sog > max_sog_kn:
                    break
                # also bound the actual displacement-speed to catch unreported sog
                dt_h = (track[j + 1].timestamp - track[j].timestamp).total_seconds() / 3600.0
                disp = haversine_nm(track[j].lat, track[j].lon,
                                    track[j + 1].lat, track[j + 1].lon)
                if dt_h > 0 and disp / dt_h > max_sog_kn:
                    break
                run.append(track[j + 1])
                j += 1
            if len(run) >= min_reports:
                dur_min = (run[-1].timestamp - run[0].timestamp).total_seconds() / 60.0
                # heading variability across the drifting run
                hdgs = [_bearing(a.lat, a.lon, b.lat, b.lon)
                        for a, b in zip(run, run[1:])
                        if haversine_nm(a.lat, a.lon, b.lat, b.lon) > 1e-4]
                swing = max((_angle_diff(x, y) for x in hdgs for y in hdgs), default=0.0)
                if dur_min >= min_minutes and swing >= min_heading_change_deg:
                    lats = [m.lat for m in run]
                    lons = [m.lon for m in run]
                    findings.append({
                        "type": "drift",
                        "mmsi": mmsi,
                        "name": run[0].name or track[0].name,
                        "duration_minutes": round(dur_min, 1),
                        "heading_swing_deg": round(swing, 1),
                        "reports": len(run),
                        "center": [round(sum(lats) / len(lats), 5),
                                   round(sum(lons) / len(lons), 5)],
                        "start": run[0].timestamp.isoformat().replace("+00:00", "Z"),
                        "end": run[-1].timestamp.isoformat().replace("+00:00", "Z"),
                        "severity": "medium",
                    })
                i = j
            else:
                i += 1
    return findings


def analyze_encounters(msgs: list[AISMessage], **kw: Any) -> dict[str, Any]:
    """Run the four interaction/behaviour detectors and return a combined report.

    Mirrors :func:`maritimeint.core.analyze` shape so it drops into the same
    exporters / risk-ranking. Tunables pass through by detector name.
    """
    cq = detect_close_quarters(
        msgs,
        cpa_nm=kw.get("cpa_nm", 0.5),
        tcpa_max_minutes=kw.get("tcpa_max_minutes", 30.0),
    )
    sh = detect_shadowing(
        msgs,
        standoff_max_nm=kw.get("standoff_max_nm", 8.0),
        min_minutes=kw.get("shadow_min_minutes", 90.0),
    )
    cv = detect_convoy(
        msgs,
        cluster_nm=kw.get("cluster_nm", 3.0),
        min_vessels=kw.get("convoy_min_vessels", 3),
    )
    dr = detect_drift(
        msgs,
        max_sog_kn=kw.get("drift_max_sog_kn", 1.5),
        min_minutes=kw.get("drift_min_minutes", 60.0),
    )
    findings = cq + sh + cv + dr
    zones = kw.get("zones")
    if zones:
        from .zones import annotate_findings
        annotate_findings(findings, zones)
    return {
        "tool": "maritimeint",
        "mode": "encounters",
        "vessels_tracked": len(_by_vessel(msgs)),
        "messages": len(msgs),
        "finding_counts": {
            "close_quarters": len(cq),
            "shadowing": len(sh),
            "convoy": len(cv),
            "drift": len(dr),
        },
        "findings": findings,
    }
