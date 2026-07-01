"""Scenario 20 - the whole pipeline, end to end.

Everything the other scenarios show, chained the way a real run works: load AIS ->
analyze (with zones) -> screen against sanctions -> prioritized watchlist -> export
to all four formats. One vertical slice from raw pings to shareable, mappable,
SIEM-ingestible intelligence. Pure offline, using the bundled Gulf fixtures.
"""
import json

from _common import messages, static_index, rule, bullet, ZONES, SANCTIONS
from maritimeint.core import analyze
from maritimeint.zones import load_zones
from maritimeint.sanctions import load_sanctions
from maritimeint.locate import locate
from maritimeint import intel


def main() -> None:
    msgs = messages()
    zones = load_zones(ZONES)
    sdn = load_sanctions(SANCTIONS)
    static = static_index(msgs)
    rule("FULL PIPELINE  -  raw AIS -> analysis -> watchlist -> four exports")

    # 1. analyze with spatial enrichment
    report = analyze(msgs, zones=zones)
    fired = [k for k, v in report["finding_counts"].items() if v]
    bullet(f"1. analyzed {report['messages']} pings from {report['vessels_tracked']} "
           f"vessels -> {len(report['findings'])} findings ({', '.join(fired)})")

    # 2. prioritized, sanctions-screened watchlist
    out = locate(msgs, sanctions=sdn, static=static, zones=zones)
    wl = out["watchlist"]
    high = [v for v in wl if v["tier"] == "HIGH"]
    bullet(f"2. watchlist of {len(wl)} vessels; {len(high)} at HIGH tier")

    # 3. export the analysis four ways
    exports = {fmt: intel.export(report, fmt) for fmt in ("geojson", "kml", "stix", "csv")}
    for fmt, text in exports.items():
        bullet(f"3. {fmt:<7} export: {len(text):>6} bytes", indent=7)

    # sanity: exports are well-formed
    assert json.loads(exports["geojson"])["type"] == "FeatureCollection"
    assert json.loads(exports["stix"])["type"] == "bundle"

    top = wl[0] if wl else None
    if top:
        flag = " [SANCTIONED]" if top["sanctioned"] else ""
        print(f"\nlead vessel: {top['mmsi']} ({top['name']}) tier={top['tier']}{flag}")
        for r in top["reasons"][:4]:
            bullet(r, indent=7)
    print("\nRaw pings in, shareable intelligence out - offline, no keys, stdlib only.")


if __name__ == "__main__":
    main()
