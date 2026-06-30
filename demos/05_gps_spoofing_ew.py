"""Scenario 5 - GPS-spoofing / electronic-warfare analyst.

Sanctioned hulls are not the only thing AIS reveals. Near conflict zones, GPS
spoofing and jamming leave two distinct fingerprints in the position data: a single
vessel's track tracing a tight *circle* (the "ships circling an airport" artifact),
and *many* vessels snapping to one synthetic position inside a short window (a
jamming hotspot). maritimeint's `detect_gps_anomalies` finds both with pure
relative-geometry math - no almanac, no signal capture, just the broadcast tracks.
Offline, on the bundled fixture.
"""
from _common import messages, rule, bullet
from maritimeint.core import detect_gps_anomalies, detect_spoofing


def main() -> None:
    msgs = messages()
    name_of = {m.mmsi: m.name for m in msgs}
    rule("GPS SPOOFING / EW  -  circling tracks & jamming hotspots in the AIS")

    gps = detect_gps_anomalies(msgs)
    circles = [f for f in gps if f["type"] == "circle_spoof"]
    jams = [f for f in gps if f["type"] == "gps_jamming"]

    print(f"\ncircle_spoof: {len(circles)}   gps_jamming: {len(jams)}\n")

    print("Circling tracks (single hull, full compass coverage in a tight radius):")
    for c in circles:
        bullet(f"{name_of.get(c['mmsi'], c['mmsi']):<10} arc {c['arc_degrees']} deg "
               f"in {c['radius_nm']}nm over {c['reports']} reports "
               f"@ {c['center']}")

    if jams:
        print("\nJamming hotspots (many vessels pinned to one synthetic position):")
        for j in jams:
            bullet(f"{j['vessel_count']} vessels at {j['position']} "
                   f"({j['window_start']} -> {j['window_end']})")
    else:
        print("\nNo jamming hotspot in this fixture (needs >=3 vessels snapped to "
              "one point).")

    print("\nFor contrast, the identity/position spoofing detector (name swaps, "
          "static pins):")
    for s in detect_spoofing(msgs):
        if s["type"] == "identity_conflict":
            bullet(f"{s['mmsi']} broadcast multiple names: {', '.join(s['names'])}")
        else:
            bullet(f"{s['mmsi']} static-pinned {s.get('reports')}x at "
                   f"{s.get('position')}")

    print("\nThese are detections over open broadcast data for situational "
          "awareness -\nnot navigation, not a fix correction, not targeting.")


if __name__ == "__main__":
    main()
