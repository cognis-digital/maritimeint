"""Scenario 15 - a compliance CI gate over a fleet snapshot.

A compliance team wants a single yes/no: does today's AIS snapshot contain any vessel
at or above a risk tier? `locate` produces the prioritized watchlist; this scenario
shows how a pipeline would gate on it (the CLI's `--fail-on` does the same and exits
non-zero). Runs sanctions screening against the bundled Gulf sanctions list. Offline.
"""
from _common import messages, static_index, rule, bullet, SANCTIONS
from maritimeint.locate import locate
from maritimeint.sanctions import load_sanctions


TIER_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


def main() -> None:
    msgs = messages()
    sdn = load_sanctions(SANCTIONS)
    static = static_index(msgs)
    rule("COMPLIANCE GATE  -  would this snapshot fail a 'no HIGH-risk vessel' policy?")

    out = locate(msgs, sanctions=sdn, static=static)
    wl = out["watchlist"]

    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for v in wl:
        counts[v["tier"]] = counts.get(v["tier"], 0) + 1
    print(f"\nwatchlist: {len(wl)} vessels  "
          f"(HIGH {counts['HIGH']}, MEDIUM {counts['MEDIUM']}, LOW {counts['LOW']})\n")

    for policy in ("HIGH", "MEDIUM"):
        worst = max((TIER_ORDER.get(v["tier"], 0) for v in wl), default=0)
        fails = worst >= TIER_ORDER[policy]
        bullet(f"policy 'fail on {policy}+'  ->  "
               f"{'FAIL (gate would block)' if fails else 'pass'}")

    top = wl[0] if wl else None
    if top:
        flag = " [SANCTIONED]" if top["sanctioned"] else ""
        print(f"\nhighest-risk vessel: {top['mmsi']} ({top['name']}) "
              f"tier={top['tier']}{flag}")


if __name__ == "__main__":
    main()
