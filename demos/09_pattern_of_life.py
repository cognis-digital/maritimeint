"""Scenario 9 - pattern-of-life baselines.

Before an anomaly means anything, you need the routine it deviates from.
`pattern_of_life` summarises each vessel's baseline over the window: reporting span,
active hours-of-day, area of operation (bounding box + centroid + extent), typical
and peak speed, and how often it went dark or loitered. It is the descriptive
maritime-domain-awareness layer - the "normal" an analyst learns first. Pure offline
analysis on the bundled Gulf fixture.
"""
from _common import messages, rule, bullet
from maritimeint.patterns import pattern_of_life


def main() -> None:
    msgs = messages()
    rule("PATTERN OF LIFE  -  per-vessel behavioural baselines")

    pol = pattern_of_life(msgs, gap_hours=6.0)
    print(f"\nbaselines for {len(pol)} vessels (most eventful first):\n")
    for p in pol:
        hrs = p["active_hours_utc"]
        hr_span = f"{hrs[0]:02d}h-{hrs[-1]:02d}h UTC" if hrs else "n/a"
        bullet(f"{p['mmsi']:<12} {p['name']:<16} span {p['span_hours']}h  "
               f"active {hr_span}")
        bullet(f"   area extent {p['area_extent_nm']}nm  centroid {p['centroid']}  "
               f"mean {p['mean_sog_kn']}kn / max {p['max_sog_kn']}kn", indent=7)
        flags = []
        if p["dark_events"]:
            flags.append(f"{p['dark_events']} dark event(s)")
        if p["loiter_events"]:
            flags.append(f"{p['loiter_events']} loiter event(s)")
        if flags:
            bullet("   behaviour: " + ", ".join(flags), indent=7)

    print("\nThe baseline is the reference frame: a vessel drifting into a new EEZ or\n"
          "going dark for the first time only reads as anomalous against its own norm.")


if __name__ == "__main__":
    main()
