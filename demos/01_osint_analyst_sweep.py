"""Scenario 1 - maritime OSINT analyst.

You have a day of AIS for a patch of the Persian Gulf and one question: *which of
these vessels deserves my attention, and why?* maritimeint runs the full detector
suite over the raw position reports and hands back a scored risk ranking with the
behaviours that drove each score - turning 61 anonymous pings from 7 vessels into a
short, explained shortlist. Pure offline analysis of the bundled fixture.
"""
from _common import messages, rule, bullet
from maritimeint.core import analyze


def main() -> None:
    msgs = messages()
    rule("MARITIME OSINT SWEEP  -  61 pings -> a scored, explained shortlist")

    report = analyze(msgs)
    print(f"\nTracked {report['vessels_tracked']} vessels across "
          f"{report['messages']} AIS reports.\n")

    print("Detector tally (what the suite found):")
    for kind, n in report["finding_counts"].items():
        if n:
            bullet(f"{kind:<16} {n}")

    print("\nRisk ranking (composite score, highest first):")
    name_of = {m.mmsi: m.name for m in msgs}
    for row in report["risk_ranking"][:6]:
        mmsi = row["mmsi"]
        print(f"     {row['risk_score']:>3}  {mmsi}  {name_of.get(mmsi, '')}")

    # explain the top vessel from its own findings
    top = report["risk_ranking"][0]["mmsi"]
    print(f"\nWhy '{name_of.get(top, top)}' ({top}) tops the list:")
    for f in report["findings"]:
        if f.get("mmsi") == top or top in f.get("vessels", []):
            bullet(f"{f['type']:<16} severity={f.get('severity', '?')}")

    clean = [m for m in name_of
             if m not in {r["mmsi"] for r in report["risk_ranking"]}]
    print(f"\n{len(clean)} vessel(s) raised no flag at all - the analyst can set "
          "them aside\nand spend the day on the ranked few. That is the whole point.")


if __name__ == "__main__":
    main()
