"""Scenario 6 - fleet network / link analysis.

A single vessel's anomalies rarely tell the whole story; coordination does. This
scenario builds the *contact network* over the bundled fixture - nodes are vessels,
edges are physical interactions (rendezvous, dark-rendezvous, close-quarters,
shadowing, convoy co-membership) - then collapses the graph into *fleet rings*:
connected clusters of vessels that repeatedly interact. That turns N isolated tracks
into the handful of groups an analyst should actually look at. Pure offline analysis.
"""
from _common import messages, rule, bullet
from maritimeint.fleet import contact_network, fleet_rings


def main() -> None:
    msgs = messages()
    rule("FLEET NETWORK  -  who interacts with whom, and which vessels cluster")

    net = contact_network(msgs)
    print(f"\ncontact graph: {len(net['nodes'])} vessels, {len(net['edges'])} interaction edge(s)\n")

    print("Interaction edges (physical contact between two hulls):")
    if not net["edges"]:
        print("  (no interactions in this fixture window)")
    for e in net["edges"]:
        bullet(f"{' <-> '.join(e['vessels'])}  [{e['severity']:>6}]  "
               f"{', '.join(e['interactions'])}  (weight {e['weight']})")

    rings = fleet_rings(msgs)
    print(f"\nFleet rings (clusters of repeatedly-interacting vessels): {len(rings)}")
    for r in rings:
        flags = ", ".join(r["flags"])
        multi = "  MULTI-FLAG" if r["multi_flag"] else ""
        bullet(f"{r['vessel_count']} vessels [{r['severity']}] via {', '.join(r['interactions'])}"
               f"  flags={flags}{multi}")
        bullet(f"   members: {', '.join(r['vessels'])}", indent=7)

    print("\nLink analysis surfaces coordination that per-vessel anomaly detection\n"
          "misses - a ring is one analyst look instead of N unrelated tracks.")


if __name__ == "__main__":
    main()
