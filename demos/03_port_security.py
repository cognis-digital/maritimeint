"""Scenario 3 - port security & force protection.

A port / maritime-security watch cares about *where* things happen relative to the
areas they own: did a vessel enter the war-risk box, call at a sanctioned terminal,
or close inside the standoff perimeter? This scenario layers the spatial picture on
top of the behavioural one - geofenced zones, inferred port-call itineraries, the
dark-rendezvous (one tanker goes dark while another loiters at the spot), and
CPA/TCPA close-quarters (a converging unknown contact). Everything offline, on the
bundled fixture and zone file.
"""
from _common import messages, rule, bullet, ZONES
from maritimeint.zones import load_zones, detect_zone_transits
from maritimeint.ports import detect_port_calls, sequence_itineraries
from maritimeint.core import detect_dark_rendezvous
from maritimeint.encounters import detect_close_quarters


def main() -> None:
    msgs = messages()
    zones = load_zones(ZONES)
    name_of = {m.mmsi: m.name for m in msgs}
    rule("PORT SECURITY / FORCE PROTECTION  -  where it happened, not just what")

    print("\n1) Zone transits (high-interest areas only):")
    for t in detect_zone_transits(msgs, zones):
        if t["zone_kind"] in ("sanctioned_port", "war_risk", "exclusion"):
            bullet(f"{name_of.get(t['mmsi'], t['mmsi']):<16} -> {t['zone']} "
                   f"[{t['zone_kind']}]  dwell {t['dwell_hours']}h")

    print("\n2) Port-call itineraries that touched a risk port:")
    calls = detect_port_calls(msgs)
    for it in sequence_itineraries(calls):
        if it["risk_ports_visited"]:
            bullet(f"{it['name']:<16} {' -> '.join(it['calls'])}   "
                   f"RISK: {', '.join(it['risk_ports_visited'])}")

    print("\n3) Dark-rendezvous (the move plain rendezvous can't see):")
    for d in detect_dark_rendezvous(msgs):
        a, b = d["vessels"]
        bullet(f"{name_of.get(a, a)} went dark {d['gap_hours']}h; "
               f"{name_of.get(b, b)} loitered {d['min_distance_nm']}nm away")

    print("\n4) Close-quarters / standoff breach (CPA-TCPA, separation only):")
    for c in detect_close_quarters(msgs):
        a, b = c["vessels"]
        bullet(f"{name_of.get(a, a)} & {name_of.get(b, b)}: CPA "
               f"{c.get('cpa_nm', '?')}nm in {c.get('tcpa_minutes', '?')}min")

    print("\nThe security picture is now spatial: which hull, in which box, doing "
          "what,\nand who closed on whom. CPA/TCPA is separation math - never an "
          "intercept.")


if __name__ == "__main__":
    main()
