"""Multi-level interactive menu for MARITIMEINT — drive the whole workflow
without memorizing flags: load AIS data, analyze, screen against a sanctions list,
build the prioritized watchlist, drill into a vessel, and export. Pure stdlib."""

from __future__ import annotations

import json

from maritimeint.core import analyze, load_messages
from maritimeint.locate import locate
from maritimeint.sanctions import load_sanctions

MENU = """
============== MARITIMEINT ==============
  data: {data}    sanctions: {sanc}
  1) Load AIS data            4) Locate — prioritized watchlist
  2) Analyze (counts + risk)  5) Vessel detail
  3) Load sanctions list      6) Export watchlist -> JSON
  0) Quit
========================================
"""


def _static(msgs) -> dict:
    out: dict[str, dict] = {}
    for m in msgs:
        if m.mmsi not in out and getattr(m, "name", ""):
            out[m.mmsi] = {"name": m.name}
    return out


def run(default_input: str = "demos/ais_sample.json", *, _input=input) -> int:
    msgs = None
    sanctions: list | None = None
    data_path = "(none)"
    sanc_path = "(none)"
    while True:
        print(MENU.format(data=data_path, sanc=sanc_path))
        try:
            choice = _input("select> ").strip()
        except EOFError:
            return 0
        if choice == "0":
            print("fair winds."); return 0
        elif choice == "1":
            p = _input(f"  AIS JSON path [{default_input}]: ").strip() or default_input
            try:
                msgs = load_messages(p); data_path = p
                print(f"  loaded {len(msgs)} messages, {len({m.mmsi for m in msgs})} vessels")
            except Exception as exc:
                print(f"  error: {exc}")
        elif choice == "3":
            p = _input("  sanctions JSON path [demos/sanctions_sample.json]: ").strip() or "demos/sanctions_sample.json"
            try:
                sanctions = load_sanctions(p); sanc_path = p
                print(f"  loaded {len(sanctions)} sanctions entries")
            except Exception as exc:
                print(f"  error: {exc}")
        elif choice in ("2", "4", "5", "6"):
            if not msgs:
                print("  load AIS data first (option 1)."); continue
            if choice == "2":
                rep = analyze(msgs)
                print(f"  vessels={rep['vessels_tracked']} messages={rep['messages']}")
                for k, v in rep["finding_counts"].items():
                    print(f"    {k:<12} {v}")
                print("  risk ranking:")
                for row in rep["risk_ranking"][:10]:
                    print(f"    {row['mmsi']:<12} score={row['risk_score']}")
            elif choice == "4":
                wl = locate(msgs, sanctions=sanctions, static=_static(msgs))["watchlist"]
                print(f"  watchlist ({len(wl)} vessels):")
                for v in wl:
                    flag = " [SANCTIONED]" if v["sanctioned"] else ""
                    print(f"    [{v['tier']:<6}] {v['mmsi']} {v['name']}{flag}  score={v['score']}")
                    for r in v["reasons"]:
                        print(f"         - {r}")
            elif choice == "5":
                mmsi = _input("  mmsi: ").strip()
                hits = [f for f in analyze(msgs)["findings"]
                        if f.get("mmsi") == mmsi or mmsi in f.get("vessels", [])]
                print(f"  {len(hits)} finding(s) for {mmsi}:")
                for f in hits:
                    print(f"    [{f.get('severity','?'):>6}] {f.get('type')}")
            elif choice == "6":
                out = _input("  output path [watchlist.json]: ").strip() or "watchlist.json"
                with open(out, "w", encoding="utf-8") as fh:
                    json.dump(locate(msgs, sanctions=sanctions, static=_static(msgs)), fh, indent=2)
                print(f"  wrote {out}")
        else:
            print("  ?")
