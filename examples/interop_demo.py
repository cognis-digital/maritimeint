#!/usr/bin/env python3
"""maritimeint interop demo - the suite as one composable pipeline.

Runs the real maritimeint core end-to-end, entirely offline from the bundled
fixtures, then chains the watchlist through the wider Cognis suite:

    import-sanctions (OFAC fixture)
        -> fetch-ais     (provider fixture, field-normalized)
        -> locate        (risk + sanctions cross-reference)   [maritimeint, always runs]
        -> humind        (extract entities / affect / salience) [optional sibling repo]
        -> agentlex      (KB facts + Horn rule -> escalate())   [optional sibling repo]
        -> edgemesh /v1  (write the human brief)                [optional model backend]

Every hop after `locate` degrades gracefully: if the sibling tool or a model
backend isn't installed/reachable, the demo prints what *would* happen and keeps
going. Install the siblings (and point MARITIMEINT_ENDPOINT/OPENAI_BASE_URL at an
edgemesh gateway) to light up the full chain. Pure standard library.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEMOS = os.path.join(ROOT, "demos")


def rule(title: str) -> None:
    print("\n" + "=" * 64 + f"\n  {title}\n" + "=" * 64)


def main() -> int:
    from maritimeint import ais_fetch, ofac
    from maritimeint.core import load_messages
    from maritimeint.locate import locate
    from maritimeint.sanctions import load_sanctions

    # 1 + 2 -- build a sanctions list and normalize an AIS feed (both offline fixtures)
    rule("1/2  import-sanctions (OFAC) + fetch-ais (provider export)")
    sanc_path = os.path.join(DEMOS, "_demo_sanctions.json")
    with open(os.path.join(DEMOS, "ofac_sdn_sample.csv"), encoding="utf-8") as fh:
        ofac.write_sanctions(ofac.to_sanctions(fh.read()), sanc_path)
    records = ais_fetch.from_file(os.path.join(DEMOS, "ais_provider_sample.csv"))
    print(f"  sanctioned vessels loaded : {len(load_sanctions(sanc_path))}")
    print(f"  AIS records normalized    : {len(records)} (provider export -> maritimeint shape)")

    # 3 -- maritimeint: risk + sanctions cross-reference (this part always runs).
    # Analyze the bundled multi-point feed (fetch-ais produces exactly this shape; the
    # 2-point provider sample above just demonstrates normalization).
    rule("3    locate  ->  prioritized, explained watchlist")
    ais_path = os.path.join(DEMOS, "ais_sample.json")
    msgs = load_messages(ais_path)
    static = {m.mmsi: {"name": m.name} for m in msgs}
    watch = locate(msgs, sanctions=load_sanctions(sanc_path), static=static)["watchlist"]
    for v in watch:
        flag = "  [SANCTIONED]" if v["sanctioned"] else ""
        print(f"  {v['tier']:<6} score={v['score']:<3} {v['name'] or v['mmsi']}{flag}")
    flagged = [v for v in watch if v["sanctioned"]]

    # 4 -- humind: cognitive extraction over each flagged vessel's narrative
    rule("4    humind  ->  cognitive extraction (entities / salience)")
    narratives = [f"{v['name']} ({v['mmsi']}): " + "; ".join(v["reasons"]) for v in flagged]
    try:
        from humind import Mind  # type: ignore
        mind = Mind()
        for text in narratives:
            mind.perceive(text)
        print(f"  humind ingested {len(narratives)} narrative(s); working memory primed.")
    except Exception:
        print("  [humind not installed - would extract entities/intent/affect/salience]")
        for text in narratives:
            print(f"    perceive: {text}")

    # 5 -- agentlex: hold facts, fire a Horn rule to escalate sanctioned hulls
    rule("5    agentlex  ->  KB facts + rule  ->  escalate(vessel)")
    try:
        from agentlex import KnowledgeBase, parse_term  # type: ignore
        kb = KnowledgeBase()
        for v in flagged:
            kb.assert_fact(parse_term(f'sanctioned("{v["mmsi"]}")'))
        kb.add_rule(parse_term("escalate(X)"), [parse_term("sanctioned(X)")])
        esc = kb.query(parse_term("escalate(X)"))
        print(f"  rule fired -> escalate/1 holds for {len(list(esc))} vessel(s).")
    except Exception:
        print('  [agentlex not installed - would assert sanctioned(MMSI), rule:')
        print('     escalate(X) :- sanctioned(X).  -> escalate() for each flagged hull]')
        for v in flagged:
            print(f"    escalate({v['mmsi']})  # {v['name']}")

    # 6 -- edgemesh /v1: write the human brief (any reachable OpenAI-compatible backend)
    rule("6    edgemesh /v1  ->  human brief")
    brief = brief_via_backend(flagged)
    print(brief)

    try:
        os.remove(sanc_path)
    except OSError:
        pass
    print("\nchain complete. Install siblings + point at an edgemesh gateway to light up 4-6.")
    return 0


def brief_via_backend(flagged: list[dict]) -> str:
    """Ask a reachable /v1 to write the brief; fall back to a deterministic local one."""
    base = os.environ.get("MARITIMEINT_ENDPOINT") or os.environ.get("OPENAI_BASE_URL")
    facts = "; ".join(f"{v['name']} ({v['mmsi']}) - {', '.join(v['reasons'])}" for v in flagged) \
        or "no sanctioned vessels in this sample"
    if base:
        try:
            import json
            import urllib.request
            url = base.rstrip("/") + "/chat/completions"
            payload = json.dumps({
                "model": os.environ.get("MARITIMEINT_MODEL", "local"),
                "messages": [
                    {"role": "system", "content": "You are a maritime watch officer. One paragraph."},
                    {"role": "user", "content": f"Brief the watch on these flagged vessels: {facts}"},
                ],
            }).encode()
            req = urllib.request.Request(url, payload, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            return "  " + data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            return f"  [backend at {base} unreachable: {exc}]\n  " + _local_brief(facts)
    return "  [no /v1 backend set - local brief]\n  " + _local_brief(facts)


def _local_brief(facts: str) -> str:
    return (f"WATCH BRIEF: {facts}. Recommend continuous track, ownership/finance pivot "
            f"(corpmap/cryptotrace), and imagery geolocation (locateanything) on next port call.")


if __name__ == "__main__":
    raise SystemExit(main())
