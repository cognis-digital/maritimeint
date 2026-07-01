"""Scenario 17 - the whole track-interaction suite at once.

`analyze_encounters` runs all four interaction/behaviour detectors - close-quarters
(CPA/TCPA), shadowing, convoy, and drift - and returns one combined, JSON-shaped
report that drops into the same exporters and risk workflow as core.analyze. This is
the one-call "how do these tracks relate to each other?" view. Pure offline.
"""
from _common import messages, rule, bullet
from maritimeint.encounters import analyze_encounters


def main() -> None:
    msgs = messages()
    rule("ENCOUNTERS SUITE  -  close-quarters + shadowing + convoy + drift, one call")

    report = analyze_encounters(msgs)
    print(f"\nTracked {report['vessels_tracked']} vessels across "
          f"{report['messages']} reports.\n")

    print("Interaction/behaviour tally:")
    for kind, n in report["finding_counts"].items():
        bullet(f"{kind:<16} {n}")

    print(f"\n{len(report['findings'])} interaction finding(s) total. Each is a plain "
          "dict that\nserialises straight to GeoJSON/KML/STIX/CSV via the intel module.")


if __name__ == "__main__":
    main()
