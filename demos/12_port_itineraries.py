"""Scenario 12 - trade-pattern analysis: port-call itineraries.

Infer *port calls* from dwell inside a port's radius, then sequence each vessel's
calls into an itinerary and flag legs that touch a sanctioned / high-risk port - the
classic laundering shape (load at a sanctioned port, sail to a clean hub to sell).
`detect_port_calls` + `sequence_itineraries`, against the built-in port registry.
Pure offline analysis of the bundled fixture.
"""
from _common import messages, rule, bullet
from maritimeint.ports import detect_port_calls, sequence_itineraries


def main() -> None:
    msgs = messages()
    rule("TRADE PATTERNS  -  port-call itineraries, risk-flagged")

    calls = detect_port_calls(msgs, min_dwell_hours=1.0)
    print(f"\n{len(calls)} port call(s) inferred from dwell. Sequencing itineraries:\n")

    itineraries = sequence_itineraries(calls)
    if not itineraries:
        print("  (no port calls in this fixture window)")
    for it in itineraries:
        risk = it["risk_ports_visited"]
        tag = f"  RISK PORTS: {', '.join(risk)}" if risk else ""
        bullet(f"[{it['severity']:>4}] {it['mmsi']} ({it['name']}): "
               f"{' -> '.join(it['calls'])}{tag}")
        for leg in it["legs"]:
            if leg["touches_risk_port"]:
                bullet(f"risky leg  {leg['from']} -> {leg['to']}", indent=9)
    print("\nItineraries turn scattered calls into a laundering-shaped narrative "
          "an analyst\ncan act on.")


if __name__ == "__main__":
    main()
