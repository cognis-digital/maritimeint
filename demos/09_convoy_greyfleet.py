"""Scenario 9 - grey-fleet flotillas move together (convoy detection).

Escort groups and shepherded grey-fleet flotillas look like several unrelated tracks
to a per-vessel detector. `detect_convoy` clusters vessels that are spatially tight
*and* share heading and speed across multiple time epochs, surfacing the coordinated
formation as one object. Pure offline analysis of the bundled fixture.
"""
from _common import messages, rule, bullet
from maritimeint.encounters import detect_convoy


def main() -> None:
    msgs = messages()
    rule("CONVOY  -  vessels moving together as a coordinated formation")

    for cluster in (3.0, 5.0, 8.0):
        cv = detect_convoy(msgs, cluster_nm=cluster, min_vessels=2)
        bullet(f"cluster radius {cluster:>3} nm (min 2 vessels)  ->  {len(cv)} group(s)")

    cv = detect_convoy(msgs, cluster_nm=5.0, min_vessels=2)
    print("\nDetail (cluster 5 nm, min 2 vessels):")
    if not cv:
        print("  (no co-moving groups in this window)")
    for f in cv:
        members = ", ".join(f["vessels"])
        bullet(f"{f['vessel_count']} vessels [{members}] held formation across "
               f"{f['epochs']} epoch(s) [{f['severity']}]")
    print("\nA convoy is one intelligence object, not N anonymous tracks.")


if __name__ == "__main__":
    main()
