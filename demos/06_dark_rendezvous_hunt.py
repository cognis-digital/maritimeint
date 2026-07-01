"""Scenario 6 - the dark ship-to-ship hunt.

The classic sanctions-evasion move: a tanker switches off AIS, a lightering vessel
loiters where it vanished, cargo changes hands in the dark. `detect_rendezvous`
needs *both* parties broadcasting; `detect_dark_rendezvous` catches the case where
one goes silent by correlating an AIS gap in vessel A with vessel B still reporting
inside A's dark window and near where A disappeared. Pure offline analysis.
"""
from _common import messages, rule, bullet
from maritimeint.core import detect_gaps, detect_dark_rendezvous


def main() -> None:
    msgs = messages()
    rule("DARK STS HUNT  -  correlate a vessel going dark with a loiterer at the spot")

    gaps = detect_gaps(msgs, gap_hours=6.0)
    print(f"\n{len(gaps)} AIS gap(s) ('going dark') in the picture. For each, is any "
          "other\nvessel present at the vanish point during the dark window?\n")

    dark = detect_dark_rendezvous(msgs, gap_hours=6.0, proximity_nm=5.0)
    if not dark:
        print("No dark rendezvous correlated in this fixture window.")
    for d in dark:
        bullet(f"{d['dark_vessel']} went dark {d['gap_hours']}h; "
               f"{d['present_vessel']} loitered {d['min_distance_nm']}nm away "
               f"({d['present_reports']} reports) - possible dark STS")
    print(f"\n{len(dark)} dark-STS correlation(s). This is the signal single-vessel "
          "anomaly\ndetection misses: the meeting only shows up when you cross two tracks.")


if __name__ == "__main__":
    main()
