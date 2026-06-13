"""LocateAnything runtime — the one-call grey-fleet watchlist for MARITIMEINT.

`locate()` runs the full detector suite, folds in sanctions screening, and returns a
**prioritized, explained watchlist** of vessels: each with a tier (HIGH/MEDIUM/LOW), a
composite score, and plain-language reasons an analyst can act on — the thing a
compliance/insurance/port team actually wants ("which vessels should I look at, and
why?"). Pure standard library; builds on `core.analyze`.
"""

from __future__ import annotations

from typing import Any

from maritimeint.core import analyze
from maritimeint.sanctions import screen

# human-readable reason templates per finding type
def _reason(f: dict[str, Any]) -> str:
    t = f.get("type")
    if t == "ais_gap":
        return f"AIS gap {f.get('gap_hours', '?')}h (going dark)"
    if t == "speed_jump":
        return f"implausible {f.get('implied_speed_kn', f.get('speed_kn', '?'))}kn position jump (possible spoofing)"
    if t in ("loitering", "static_pin"):
        span = f.get("span_hours")
        return (f"loitering ~{span}h (possible STS staging)" if span
                else "loitering (possible STS staging)")
    if t == "spoofing":
        return "identity/position conflict (spoofing)"
    if t == "rendezvous":
        other = [v for v in f.get("vessels", [])]
        return (f"rendezvous {f.get('duration_minutes', '?')}min, "
                f"min {f.get('min_distance_nm', '?')}nm (possible ship-to-ship transfer)")
    return t or "anomaly"


def locate(msgs, sanctions: list[dict[str, Any]] | None = None,
           static: dict[str, dict] | None = None, **kw: Any) -> dict[str, Any]:
    """Return {watchlist: [...], report: {...}}.

    `static` optionally maps mmsi -> {"name":..,"imo":..} for sanctions matching.
    """
    report = analyze(msgs, **kw)
    static = static or {}

    # group reasons per vessel from the findings
    reasons: dict[str, list[str]] = {}
    for f in report["findings"]:
        ids = []
        if "mmsi" in f:
            ids.append(f["mmsi"])
        ids += f.get("vessels", [])
        for mid in ids:
            reasons.setdefault(mid, []).append(_reason(f))

    base = {row["mmsi"]: row["risk_score"] for row in report["risk_ranking"]}
    watch: list[dict[str, Any]] = []
    for mmsi in sorted(set(base) | set(reasons)):
        meta = static.get(mmsi, {})
        hits = screen(mmsi, name=meta.get("name", ""), imo=meta.get("imo", ""),
                      sanctions=sanctions)
        score = base.get(mmsi, 0) + (5 if hits else 0)   # sanctions = strong escalation
        tier = "HIGH" if (hits or score >= 5) else "MEDIUM" if score >= 2 else "LOW"
        vreasons = sorted(set(reasons.get(mmsi, [])))
        if hits:
            progs = ", ".join(h["entry"].get("program", h["entry"].get("source", "sanctioned"))
                              for h in hits)
            vreasons.insert(0, f"ON SANCTIONS LIST ({progs})")
        watch.append({"mmsi": mmsi, "name": meta.get("name", ""), "tier": tier,
                      "score": score, "sanctioned": bool(hits), "reasons": vreasons})

    watch.sort(key=lambda v: (v["sanctioned"], v["score"]), reverse=True)
    return {"watchlist": watch, "report": report}
