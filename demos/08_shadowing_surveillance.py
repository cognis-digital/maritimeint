"""Scenario 8 - is someone being trailed? (shadowing)

Distinct from a rendezvous (which converges to contact) and a convoy (a tight
cluster abreast): shadowing is one vessel persistently *behind* another at a held
standoff on a matched course over an extended window - a documented surveillance /
interdiction / escort-precursor signature. `detect_shadowing` finds it and labels
leader vs follower by track geometry. Pure offline analysis of the bundled fixture.
"""
from _common import messages, rule, bullet
from maritimeint.encounters import detect_shadowing


def main() -> None:
    msgs = messages()
    rule("SHADOWING  -  persistent trailing at a held standoff (surveillance signature)")

    sh = detect_shadowing(msgs, standoff_max_nm=8.0, min_minutes=90.0)
    print(f"\n{len(sh)} shadowing relationship(s) sustained >= 90 min:\n")
    if not sh:
        print("  (no shadowing in this fixture window)")
    for f in sh:
        names = f.get("names", {})
        lead = f["leader"]
        follow = f["follower"]
        bullet(f"{follow} ({names.get(follow, '')}) trailing "
               f"{lead} ({names.get(lead, '')})  "
               f"mean standoff {f['mean_standoff_nm']}nm over {f['duration_minutes']}min "
               f"[{f['severity']}]")
    print("\nShadowing surfaces coordination that per-vessel anomaly detection treats "
          "as\ntwo unrelated tracks. Descriptive / defensive only.")


if __name__ == "__main__":
    main()
