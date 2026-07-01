"""Scenario 14 - push to a threat-intel platform (STIX 2.1).

A finding is only useful if it leaves the tool. `intel.to_stix` renders any
analyze() result as a valid STIX 2.1 bundle of Indicator objects, with deterministic
uuid5 ids (so re-running is byte-stable and safe to diff in a pipeline). This scenario
builds the bundle, validates its shape, and shows a sample indicator. Pure offline.
"""
import json

from _common import messages, rule, bullet
from maritimeint.core import analyze
from maritimeint import intel


def main() -> None:
    msgs = messages()
    rule("TIP EXPORT  -  analyze() -> valid STIX 2.1 bundle (deterministic ids)")

    report = analyze(msgs)
    bundle = json.loads(intel.to_stix(report))
    inds = [o for o in bundle["objects"] if o["type"] == "indicator"]

    bullet(f"bundle type: {bundle['type']}  id: {bundle['id'][:30]}...")
    bullet(f"indicators : {len(inds)}")
    assert all(o["spec_version"] == "2.1" for o in inds), "all objects must be STIX 2.1"
    assert all(o["pattern_type"] == "stix" for o in inds)

    if inds:
        s = inds[0]
        print("\nSample indicator:")
        bullet(f"name    : {s['name']}", indent=7)
        bullet(f"pattern : {s['pattern']}", indent=7)
        bullet(f"labels  : {s['labels']}", indent=7)

    again = json.loads(intel.to_stix(report))
    stable = [o["id"] for o in again["objects"]] == [o["id"] for o in bundle["objects"]]
    print(f"\nre-run produced identical ids (pipeline-safe): {stable}")


if __name__ == "__main__":
    main()
