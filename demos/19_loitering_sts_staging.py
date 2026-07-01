"""Scenario 19 - loitering as ship-to-ship staging.

A vessel that stays inside a small radius for hours in open water - away from any
port - is staging: waiting for a counterparty, holding for a transfer window, or
parked off a lightering area. `detect_loitering` finds these dwell events; sweeping
the duration threshold shows how the signal sharpens. Pure offline analysis.
"""
from _common import messages, rule, bullet
from maritimeint.core import detect_loitering


def main() -> None:
    msgs = messages()
    rule("STS STAGING  -  loitering (holding station in open water)")

    print()
    for min_h in (2.0, 4.0, 6.0):
        loiter = detect_loitering(msgs, radius_nm=2.0, min_hours=min_h)
        bullet(f"dwell >= {min_h:>3} h  ->  {len(loiter)} loiter event(s)")

    loiter = detect_loitering(msgs, radius_nm=2.0, min_hours=4.0)
    print("\nDetail (radius 2 nm, dwell >= 4 h):")
    if not loiter:
        print("  (no loitering in this fixture window)")
    for f in loiter:
        bullet(f"{f['mmsi']} ({f['name']}) held {f['duration_hours']}h within "
               f"{f['radius_nm']}nm of {f['center']} ({f['reports']} reports) "
               f"[{f['severity']}]")
    print("\nLoitering in open water is the pre-transfer tell - it puts the vessel on "
          "the\nwatchlist before any rendezvous even happens.")


if __name__ == "__main__":
    main()
