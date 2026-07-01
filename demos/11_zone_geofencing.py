"""Scenario 11 - geofencing: where did it happen? (zone transits)

An event is more actionable with a place attached. `detect_zone_transits` reports,
per vessel and per zone, entry/exit events and dwell time against analyst-defined
areas - EEZs, sanctioned ports, exclusion / war-risk zones. Severity is keyed to the
zone kind (a dwell in a sanctioned port outranks a routine EEZ transit). Loads the
bundled Gulf zone GeoJSON; pure offline analysis.
"""
from _common import messages, rule, bullet, ZONES
from maritimeint.zones import load_zones, detect_zone_transits


def main() -> None:
    msgs = messages()
    zones = load_zones(ZONES)
    rule("GEOFENCING  -  zone entries, exits and dwell against defined areas")

    print(f"\nLoaded {len(zones)} zone(s): "
          + ", ".join(f"{z.name} ({z.kind})" for z in zones) + "\n")

    transits = detect_zone_transits(msgs, zones)
    by_sev = {"high": [], "medium": [], "low": []}
    for t in transits:
        by_sev.setdefault(t["severity"], []).append(t)
    for sev in ("high", "medium", "low"):
        for t in by_sev.get(sev, []):
            bullet(f"[{sev:>6}] {t['mmsi']} ({t['name']}) in '{t['zone']}' "
                   f"({t['zone_kind']}) dwell {t['dwell_hours']}h")
    print(f"\n{len(transits)} transit event(s). Now every anomaly can be tagged with "
          "the\nzones it touched - a gap in a war-risk box reads very differently from "
          "one at sea.")


if __name__ == "__main__":
    main()
