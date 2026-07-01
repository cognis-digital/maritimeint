"""Scenario 8 - ship-to-ship-transfer correlation (multi-signal fusion).

A ship-to-ship transfer is rarely one clean event; it is a *stack* of signals: a
vessel loiters, a counterparty goes dark near it, and they sit alongside. Any one of
those alone is weak. `sts_transfer_score` anchors on each (dark_)rendezvous and folds
in overlapping loitering and going-dark by either party, producing a single *scored,
explained* STS-candidate an analyst can triage instead of three disconnected findings.
Pure offline analysis on the bundled Gulf fixture.
"""
from _common import messages, rule, bullet
from maritimeint.patterns import sts_transfer_score, gap_timeline


def main() -> None:
    msgs = messages()
    rule("STS CORRELATION  -  fusing loiter + going-dark + rendezvous into one score")

    sts = sts_transfer_score(msgs, gap_hours=6.0)
    print(f"\nSTS candidates: {len(sts)}\n")
    if not sts:
        print("  (no rendezvous anchor in this fixture window)")
    for s in sorted(sts, key=lambda x: x["score"], reverse=True):
        bullet(f"{' & '.join(s['vessels'])}  score={s['score']} [{s['severity']}]  "
               f"anchor={s['anchor']}  ({s['start']} -> {s['end']})")
        for ev in s["evidence"]:
            bullet(f"   - {ev}", indent=7)

    print("\nGoing-dark timeline (the disappearance pattern behind the score):")
    tl = gap_timeline(msgs, gap_hours=6.0)
    for t in tl:
        bullet(f"{t['mmsi']} ({t['name']})  {t['dark_events']} dark event(s), "
               f"longest {t['longest_dark_hours']}h, total {t['total_dark_hours']}h dark")

    print("\nScoring turns a bare proximity ping into an explained candidate: the\n"
          "evidence list is exactly what a reviewer needs to accept or dismiss it.")


if __name__ == "__main__":
    main()
