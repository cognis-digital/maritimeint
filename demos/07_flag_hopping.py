"""Scenario 7 - flag-hopping & identity manipulation.

Re-flagging a hull to obscure ownership, and cloning a legitimate vessel's name onto
a different MMSI, are documented sanctions-evasion tells. `flag_hopping` ties MMSIs
to a hull (by IMO when known, else by reported name) and flags a hull whose MMSIs
decode - via their MID country prefix - to more than one flag state. `identity_rings`
catches the inverse: one name on several MMSIs, or one MMSI carrying several names.

This scenario uses a small purpose-built fixture (the Gulf demo set has no re-flagged
hull) so the signal is visible; the API is the real one. Pure offline analysis.
"""
from _common import rule, bullet
from maritimeint.core import parse_messages
from maritimeint.fleet import flag_hopping, identity_rings, flag_of


# A hull that broadcast a Russia-flagged MMSI (MID 273), then re-appeared under a
# Liberia flag (MID 636) and a Panama flag (MID 351) - same reported name throughout.
_RECS = [
    {"mmsi": "273456789", "timestamp": "2026-01-01T00:00:00Z", "lat": 60.3, "lon": 28.7, "name": "AURORA K"},
    {"mmsi": "273456789", "timestamp": "2026-01-01T06:00:00Z", "lat": 59.9, "lon": 27.0, "name": "AURORA K"},
    {"mmsi": "636112233", "timestamp": "2026-02-10T00:00:00Z", "lat": 34.9, "lon": 35.9, "name": "AURORA K"},
    {"mmsi": "636112233", "timestamp": "2026-02-10T06:00:00Z", "lat": 34.5, "lon": 34.0, "name": "AURORA K"},
    {"mmsi": "351998877", "timestamp": "2026-03-05T00:00:00Z", "lat": 29.2, "lon": 50.3, "name": "AURORA K"},
    # a separate name-cloning ring: two distinct MMSIs both claiming "SEA PEARL"
    {"mmsi": "412000111", "timestamp": "2026-01-15T00:00:00Z", "lat": 29.8, "lon": 122.0, "name": "SEA PEARL"},
    {"mmsi": "563000222", "timestamp": "2026-01-15T00:00:00Z", "lat": 1.3, "lon": 103.8, "name": "SEA PEARL"},
]


def main() -> None:
    msgs = parse_messages(_RECS)
    rule("FLAG-HOPPING & IDENTITY  -  re-flagged hulls and cloned names")

    hops = flag_hopping(msgs)
    print(f"\nflag-hopping hulls: {len(hops)}\n")
    for h in hops:
        bullet(f"{h['hull']}  [{h['severity']}]  {h['flag_count']} flags: {', '.join(h['flags'])}")
        for mmsi, flag in h["mmsi_flags"].items():
            bullet(f"   {mmsi}  ->  {flag}", indent=7)

    ids = identity_rings(msgs)
    clones = [f for f in ids if f["type"] == "name_clone"]
    print(f"\nname-cloning rings: {len(clones)}")
    for c in clones:
        bullet(f"'{c['name']}' broadcast by {c['mmsi_count']} MMSIs "
               f"({', '.join(c['vessels'])}) flags={', '.join(c['flags'])}")

    print("\nHow the flag is read: the MMSI's first three digits (the MID) map to a\n"
          "flag state -", ", ".join(f"{m[:3]}={flag_of(m)}" for m in
                                     ("273456789", "636112233", "351998877")))
    print("\nA hull that keeps changing its flag, or a name that appears on multiple\n"
          "hulls, is an ownership-obfuscation signal worth a compliance look.")


if __name__ == "__main__":
    main()
