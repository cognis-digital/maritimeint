"""Scenario 18 - spatially-aware analysis (findings tagged with zones).

Run the full detector suite *with* zones and every finding that has a position is
tagged with the zones it falls in. Now an AIS gap inside a war-risk box reads
differently from one in open water, and you can filter the whole report by area.
Loads the bundled Gulf zones GeoJSON; pure offline analysis of the bundled fixture.
"""
from _common import messages, rule, bullet, ZONES
from maritimeint.core import analyze
from maritimeint.zones import load_zones


def main() -> None:
    msgs = messages()
    zones = load_zones(ZONES)
    rule("SPATIAL ANALYSIS  -  full suite, every finding tagged with its zones")

    report = analyze(msgs, zones=zones)
    tagged = [f for f in report["findings"] if f.get("zones")]

    print(f"\n{len(report['findings'])} findings; {len(tagged)} fall inside a "
          "defined zone.\n")

    # group tagged findings by zone name
    by_zone: dict[str, int] = {}
    for f in tagged:
        for z in f["zones"]:
            by_zone[z] = by_zone.get(z, 0) + 1
    if not by_zone:
        print("  (no findings intersect the loaded zones in this window)")
    for zname, n in sorted(by_zone.items(), key=lambda kv: kv[1], reverse=True):
        bullet(f"{zname:<24} {n} finding(s)")

    print("\nSame detections, now filterable by area - the spatial layer analysts "
          "actually\nreason in.")


if __name__ == "__main__":
    main()
