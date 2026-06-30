"""Generate the bundled demo AIS fixture (demos/data/gulf_scenario.json).

Deterministic, offline, hand-tuned so each demo scenario exercises a real
detector path. Re-run only if you intend to regenerate the fixture; the demos
ship the committed JSON and never call this at runtime.

    python scripts/gen_gulf_scenario.py
"""
import json
import math
import os
from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "demos", "data", "gulf_scenario.json")


def ts(h: float) -> str:
    return (BASE + timedelta(hours=h)).isoformat().replace("+00:00", "Z")


def build() -> list:
    recs = []

    # A: GREY DAWN — sanctioned tanker. Transits in, loiters (STS staging),
    #    goes dark 30h, reappears at Kharg Island (sanctioned port).
    A = "572100001"
    for h, lat, lon, sog, cog in [
        (0, 25.0, 57.0, 11, 300), (2, 25.4, 56.4, 11, 300), (4, 25.9, 55.8, 11, 305),
        (6, 26.5, 55.2, 10, 308), (8, 27.1, 54.4, 10, 310),
        (10, 28.0, 53.0, 0.3, 0), (12, 28.02, 53.01, 0.2, 0),
        (14, 28.01, 52.99, 0.3, 0), (16, 28.0, 53.0, 0.2, 0),
        (46, 29.1, 50.4, 6, 330),  # reappears after 30h dark window
        (47, 29.23, 50.32, 0.4, 0), (49, 29.23, 50.32, 0.3, 0), (51, 29.23, 50.32, 0.4, 0),
        (54, 29.0, 50.8, 9, 120), (56, 28.4, 51.6, 10, 120),
    ]:
        recs.append({"mmsi": A, "name": "GREY DAWN", "imo": "9700101",
                     "timestamp": ts(h), "lat": lat, "lon": lon, "sog": sog, "cog": cog})

    # B: LANTERN — lightering vessel loitering at the spot A went dark (dark-STS).
    B = "636200002"
    for h, lat, lon, sog, cog in [
        (12, 28.5, 52.2, 8, 250), (16, 28.3, 52.0, 7, 250),
        (20, 28.05, 52.95, 0.3, 0), (24, 28.04, 52.96, 0.2, 0), (28, 28.06, 52.94, 0.3, 0),
        (32, 28.05, 52.95, 0.2, 0), (36, 28.04, 52.96, 0.3, 0),
        (40, 28.4, 52.2, 8, 70), (44, 29.0, 51.4, 9, 70),
    ]:
        recs.append({"mmsi": B, "name": "LANTERN", "imo": "9700202",
                     "timestamp": ts(h), "lat": lat, "lon": lon, "sog": sog, "cog": cog})

    # C: CLEAN TRADER — ordinary steady passage, no anomalies (control vessel).
    #    Sampled densely (every 3h) so it never trips the going-dark gap detector.
    C = "563300003"
    for i in range(9):
        recs.append({"mmsi": C, "name": "CLEAN TRADER", "imo": "9700303",
                     "timestamp": ts(i * 3), "lat": round(12.0 + i * 0.4, 4),
                     "lon": round(80.0 - i * 0.75, 4), "sog": 14, "cog": 285})

    # D: MIRAGE — GPS-spoof circling track (tight radius, full compass coverage).
    D = "247400004"
    cx, cy = 25.3, 55.4
    for i, a in enumerate(range(0, 360, 30)):
        recs.append({"mmsi": D, "name": "MIRAGE", "timestamp": ts(i * 0.5),
                     "lat": round(cx + 0.03 * math.cos(math.radians(a)), 5),
                     "lon": round(cy + 0.03 * math.sin(math.radians(a)), 5),
                     "sog": 2, "cog": a})

    # E: SEA FOX/NIGHT FOX — one MMSI, two names + an impossible teleport.
    E = "311500005"
    recs += [
        {"mmsi": E, "name": "SEA FOX", "timestamp": ts(0), "lat": 1.2, "lon": 103.8, "sog": 10, "cog": 90},
        {"mmsi": E, "name": "SEA FOX", "timestamp": ts(1), "lat": 1.3, "lon": 104.0, "sog": 10, "cog": 90},
        {"mmsi": E, "name": "NIGHT FOX", "timestamp": ts(1.2), "lat": 5.0, "lon": 110.0, "sog": 10, "cog": 90},
        {"mmsi": E, "name": "NIGHT FOX", "timestamp": ts(3), "lat": 5.2, "lon": 110.3, "sog": 10, "cog": 90},
    ]

    # G/H: converging tracks at the Strait of Hormuz approach (close-quarters).
    G, H = "431600006", "431600007"
    for h in range(0, 6):
        recs.append({"mmsi": G, "name": "GUARDIAN", "timestamp": ts(h),
                     "lat": 26.5, "lon": 56.4 - 0.02 * h, "sog": 8, "cog": 270})
        recs.append({"mmsi": H, "name": "UNKNOWN CONTACT", "timestamp": ts(h),
                     "lat": 26.45 + 0.018 * h, "lon": 56.3 + 0.01 * h, "sog": 9, "cog": 30})

    return recs


def main() -> None:
    recs = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(recs, fh, indent=1)
    print(f"wrote {len(recs)} records "
          f"({len({r['mmsi'] for r in recs})} vessels) -> {OUT}")


if __name__ == "__main__":
    main()
