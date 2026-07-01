"""Scenario 13 - GPS spoofing artifacts (circling & jamming hotspots).

Two GPS-integrity artifacts seen near conflict zones: a single track tracing a full
circle while confined to a tiny radius (the "ships circling an airport" spoof), and
many *distinct* vessels snapped to one synthetic position in a short window (a
jamming hotspot). `detect_gps_anomalies` surfaces both from raw AIS. Pure offline.
"""
from _common import messages, rule, bullet
from maritimeint.core import detect_gps_anomalies


def main() -> None:
    msgs = messages()
    rule("GPS INTEGRITY  -  circling-spoof tracks + jamming hotspots")

    f = detect_gps_anomalies(msgs)
    circ = [x for x in f if x["type"] == "circle_spoof"]
    jam = [x for x in f if x["type"] == "gps_jamming"]

    print(f"\ncircle-spoof tracks: {len(circ)}")
    for c in circ:
        bullet(f"{c['mmsi']} ({c['name']}) traced {c['arc_degrees']} deg within "
               f"{c['radius_nm']}nm over {c['reports']} reports [{c['severity']}]")
    print(f"\njamming hotspots: {len(jam)}")
    for j in jam:
        bullet(f"{j['vessel_count']} vessels pinned to {j['position']} "
               f"({j['window_start']} .. {j['window_end']}) [{j['severity']}]")
    print("\nGPS-integrity anomalies distinguish a *sensor* failure from a *behaviour* "
          "one -\nboth matter, for different reasons.")


if __name__ == "__main__":
    main()
