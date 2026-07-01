"""Scenario 10 - safety watch: a vessel adrift (not-under-command / distress).

Not every anomaly is malicious. A vessel *adrift* creeps at near-zero speed while
its heading swings with the set of current and wind - lost propulsion, dragging
anchor, or in distress. `detect_drift` flags a run of low-SOG fixes with erratic
heading as a safety / possible-distress early warning, not an anomaly-of-intent.
Pure offline analysis of the bundled fixture.
"""
from _common import messages, rule, bullet
from maritimeint.encounters import detect_drift


def main() -> None:
    msgs = messages()
    rule("SAFETY WATCH  -  vessels adrift (not-under-command / possible distress)")

    dr = detect_drift(msgs, max_sog_kn=1.5, min_minutes=60.0)
    print(f"\n{len(dr)} vessel(s) showing an adrift signature:\n")
    if not dr:
        print("  (no drift in this fixture window)")
    for f in dr:
        bullet(f"{f['mmsi']} ({f['name']})  heading swing {f['heading_swing_deg']} deg "
               f"over {f['duration_minutes']}min at center "
               f"{f['center']} [{f['severity']}]")
    print("\nDrift is a humanitarian / safety signal - a vessel that may need "
          "assistance,\nor that has lost propulsion in a traffic lane.")


if __name__ == "__main__":
    main()
