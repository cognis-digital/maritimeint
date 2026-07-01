"""Scenario 7 - force protection / collision avoidance (CPA / TCPA).

The bridge watch-officer's question, applied to AIS history: did any contact close
inside our standoff perimeter? `detect_close_quarters` runs the same relative-motion
Closest-Point-of-Approach / Time-to-CPA math a collision-avoidance radar runs, over
every vessel pair, and flags converging tracks projected to pass within a danger
radius. This computes *separation* only - never an intercept or a maneuver. Offline.
"""
from _common import messages, rule, bullet
from maritimeint.encounters import detect_close_quarters


def main() -> None:
    msgs = messages()
    rule("FORCE PROTECTION  -  CPA/TCPA: who closes inside the standoff perimeter?")

    for cpa in (0.5, 1.0, 2.0):
        cq = detect_close_quarters(msgs, cpa_nm=cpa, tcpa_max_minutes=30.0)
        bullet(f"danger radius {cpa:>3} nm  ->  {len(cq)} converging pair(s)")

    cq = detect_close_quarters(msgs, cpa_nm=1.0, tcpa_max_minutes=45.0)
    print(f"\nDetail at 1.0 nm / 45 min:")
    if not cq:
        print("  (no converging pairs in this window)")
    for f in cq:
        bullet(f"{f['vessels'][0]} x {f['vessels'][1]}  CPA={f['cpa_nm']}nm  "
               f"TCPA={f['tcpa_minutes']}min  range={f['range_at_detection_nm']}nm "
               f"[{f['severity']}]")
    print("\nRetrospective, defensive, situational-awareness only.")


if __name__ == "__main__":
    main()
