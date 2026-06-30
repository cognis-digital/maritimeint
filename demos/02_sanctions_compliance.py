"""Scenario 2 - sanctions & trade-compliance officer.

A compliance desk does not want a pile of anomalies; it wants a *watchlist*: which
hulls to escalate, whether any are already designated, and a plain-language reason
to put in the file. `locate()` fuses the behavioural detectors with a sanctions
screen (match on MMSI / IMO / name) and tiers every vessel HIGH / MEDIUM / LOW. A
sanctions hit is a hard escalation. Screens against a bundled SAMPLE list (the same
shape as an OFAC SDN / EU / UK OFSI export) - swap in the real list with
`maritimeint import-ofac`.
"""
import json

from _common import messages, rule, bullet, SCENARIO, SANCTIONS
from maritimeint.locate import locate
from maritimeint.sanctions import load_sanctions


def main() -> None:
    msgs = messages()
    sanctions = load_sanctions(SANCTIONS)
    rule("SANCTIONS / COMPLIANCE  -  behaviour + designation -> a tiered watchlist")

    # IMO is the durable, hull-bound identity sanctions lists key on; carry it
    # from the raw fixture into the screening index (AIS position reports omit it).
    static = {m.mmsi: {"name": m.name, "imo": ""} for m in msgs}
    for rec in json.load(open(SCENARIO, encoding="utf-8")):
        if rec.get("imo"):
            static[rec["mmsi"]]["imo"] = rec["imo"]

    result = locate(msgs, sanctions=sanctions, static=static)
    watch = result["watchlist"]

    print(f"\nScreened {len(watch)} vessels against {len(sanctions)} sanctions "
          "entries (SAMPLE list).\n")
    for w in watch:
        flag = "[SANCTIONED]" if w["sanctioned"] else ""
        print(f"  {w['tier']:<6} score={w['score']:<3} {w['mmsi']}  "
              f"{w['name'] or '(no name)':<16}{flag}")

    print("\nFile note for the top escalation:")
    top = watch[0]
    print(f"  Vessel {top['name'] or top['mmsi']} ({top['mmsi']}) - tier {top['tier']}")
    for r in top["reasons"]:
        bullet(r)

    hits = [w for w in watch if w["sanctioned"]]
    print(f"\n{len(hits)} of {len(watch)} vessels matched the sanctions list and "
          "were auto-escalated\nto HIGH regardless of behaviour score. Designation "
          "is never a soft signal.")


if __name__ == "__main__":
    main()
