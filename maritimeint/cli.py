"""Command-line interface for MARITIMEINT."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import TOOL_NAME, TOOL_VERSION
from .core import (
    load_messages,
    detect_gaps,
    detect_speed_jumps,
    detect_loitering,
    detect_spoofing,
    detect_rendezvous,
    analyze,
)
from .locate import locate
from .sanctions import load_sanctions


def _emit(obj: Any, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(obj, indent=2))
        return
    if isinstance(obj, dict) and "watchlist" in obj:
        wl = obj["watchlist"]
        print(f"MARITIMEINT watchlist ({len(wl)} vessels, highest risk first):")
        for v in wl:
            flag = " [SANCTIONED]" if v["sanctioned"] else ""
            print(f"  [{v['tier']:<6}] {v['mmsi']} {v['name']}{flag}  score={v['score']}")
            for r in v["reasons"]:
                print(f"        - {r}")
        if obj.get("ai_assessment"):
            print("\nAI assessment (reasoning add-in):\n" + obj["ai_assessment"])
        return
    # table
    if isinstance(obj, dict) and "findings" in obj:
        print(f"MARITIMEINT report  vessels={obj['vessels_tracked']}  "
              f"messages={obj['messages']}")
        print("finding counts:")
        for k, v in obj["finding_counts"].items():
            print(f"  {k:<12} {v}")
        print("risk ranking:")
        for row in obj["risk_ranking"]:
            print(f"  {row['mmsi']:<12} score={row['risk_score']}")
        print(f"findings ({len(obj['findings'])}):")
        rows = obj["findings"]
    else:
        rows = obj if isinstance(obj, list) else [obj]
        print(f"findings ({len(rows)}):")
    for f in rows:
        sev = f.get("severity", "?")
        ident = f.get("mmsi") or ",".join(f.get("vessels", []))
        print(f"  [{sev:>6}] {f.get('type'):<16} {ident}")


def _add_input(p: argparse.ArgumentParser) -> None:
    p.add_argument("input", help="path to AIS JSON file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="AIS vessel tracking & sanctions-evasion anomaly detection.",
    )
    parser.add_argument("--version", action="version",
                        version=f"{TOOL_NAME} {TOOL_VERSION}")
    parser.add_argument("--format", choices=["table", "json"], default="table",
                        help="output format (default: table)")
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="run full detector suite + risk ranking")
    _add_input(a)

    g = sub.add_parser("gaps", help="detect AIS reporting gaps (going dark)")
    _add_input(g)
    g.add_argument("--gap-hours", type=float, default=6.0)

    j = sub.add_parser("jumps", help="detect implausible position jumps")
    _add_input(j)
    j.add_argument("--max-speed-kn", type=float, default=40.0)

    l = sub.add_parser("loiter", help="detect loitering / STS staging")
    _add_input(l)
    l.add_argument("--radius-nm", type=float, default=2.0)
    l.add_argument("--min-hours", type=float, default=4.0)

    s = sub.add_parser("spoof", help="detect spoofing / identity conflicts")
    _add_input(s)

    r = sub.add_parser("rendezvous", help="detect vessel-to-vessel meetings")
    _add_input(r)
    r.add_argument("--proximity-nm", type=float, default=0.5)
    r.add_argument("--min-minutes", type=float, default=30.0)

    lo = sub.add_parser("locate", help="prioritized + explained grey-fleet watchlist")
    _add_input(lo)
    lo.add_argument("--sanctions", default=None, help="sanctions list JSON to cross-reference")
    lo.add_argument("--ai", action="store_true",
                    help="augment with the reasoning add-in if a model backend is reachable")
    lo.add_argument("--endpoint", default=None,
                    help="OpenAI-compatible base URL for add-ins (e.g. a live edgemesh gateway)")
    lo.add_argument("--model", default=None, help="model id for the add-in")
    lo.add_argument("--fail-on", choices=["low", "medium", "high"], default=None,
                    help="exit non-zero if any vessel is at/above this tier (compliance/CI gate)")

    vi = sub.add_parser("vision", help="triage maritime imagery for vessel presence (VL add-in)")
    vi.add_argument("image", help="image URL or data URI (e.g. a Sentinel-1/optical scene)")
    vi.add_argument("--endpoint", default=None, help="OpenAI-compatible VL base URL (live edgemesh gateway)")
    vi.add_argument("--model", default=None)
    vi.add_argument("--note", default="", help="optional context for the triage")

    sub.add_parser("menu", help="interactive multi-level menu")
    sub.add_parser("addins", help="show available AI add-ins (VL + reasoning) and their backends")

    io = sub.add_parser("import-ofac", help="fetch the live OFAC SDN list -> a --sanctions JSON of designated vessels")
    io.add_argument("--out", default="ofac_sanctions.json", help="output sanctions JSON path")
    io.add_argument("--from-file", default=None, help="parse a local SDN.csv instead of fetching")
    io.add_argument("--url", default=None, help="override the SDN.csv URL")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "menu":  # pragma: no cover - interactive
        from .menu import run as menu_run
        return menu_run()
    if args.command == "addins":
        from .addins import available
        rows = available()
        if args.format == "json":
            print(json.dumps(rows, indent=2))
        else:
            print("AI add-ins (stack onto the stdlib detection core):")
            for a in rows:
                st = f"ENABLED via {a['backend']}" if a["enabled"] else "disabled (no backend reachable)"
                print(f"  {a['addin']:<10} {st}")
                print(f"             {a['capability']}")
        return 0
    if args.command == "vision":
        from .addins import available, vision_assess
        if args.endpoint:
            base, model = args.endpoint, (args.model or "default")
        else:
            a = next((x for x in available() if x["addin"] == "vision" and x["enabled"]), None)
            if not a:
                print("no vision backend reachable; start a VL backend (e.g. vision-fleet) "
                      "or pass --endpoint <edgemesh /v1 base>", file=sys.stderr)
                return 1
            base, model = a["base_url"], (args.model or (a["models"] or ["default"])[0])
        try:
            print(vision_assess(args.image, base, model, note=args.note))
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "import-ofac":
        from . import ofac
        try:
            if args.from_file:
                with open(args.from_file, encoding="utf-8") as fh:
                    text = fh.read()
            else:
                text = ofac.fetch_sdn(args.url or ofac.SDN_CSV_URL)
            entries = ofac.to_sanctions(text)
            ofac.write_sanctions(entries, args.out)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        with_imo = sum(1 for e in entries if e["imo"])
        print(f"wrote {len(entries)} sanctioned vessels ({with_imo} with IMO) to {args.out}")
        print(f"use it:  maritimeint locate <ais.json> --sanctions {args.out}")
        return 0

    try:
        msgs = load_messages(args.input)
        if args.command == "analyze":
            result: Any = analyze(msgs)
        elif args.command == "locate":
            sanctions = load_sanctions(args.sanctions) if args.sanctions else None
            static = {m.mmsi: {"name": m.name} for m in msgs}
            result = locate(msgs, sanctions=sanctions, static=static)
            if args.ai or args.endpoint:
                from .addins import available, reasoning_assess
                if args.endpoint:
                    base, model = args.endpoint, (args.model or "default")
                else:
                    a = next((x for x in available() if x["addin"] == "reasoning" and x["enabled"]), None)
                    base, model = (a["base_url"], args.model or (a["models"] or ["default"])[0]) if a else (None, None)
                if base:
                    try:
                        result["ai_assessment"] = reasoning_assess(result["watchlist"], base, model)
                    except Exception as exc:
                        result["ai_assessment"] = f"(reasoning add-in error: {exc})"
                else:
                    result["ai_assessment"] = "(no reasoning backend reachable; core watchlist only)"
        elif args.command == "gaps":
            result = detect_gaps(msgs, gap_hours=args.gap_hours)
        elif args.command == "jumps":
            result = detect_speed_jumps(msgs, max_speed_kn=args.max_speed_kn)
        elif args.command == "loiter":
            result = detect_loitering(msgs, radius_nm=args.radius_nm,
                                      min_hours=args.min_hours)
        elif args.command == "spoof":
            result = detect_spoofing(msgs)
        elif args.command == "rendezvous":
            result = detect_rendezvous(msgs, proximity_nm=args.proximity_nm,
                                       min_minutes=args.min_minutes)
        else:  # pragma: no cover
            parser.error(f"unknown command {args.command}")
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _emit(result, args.format)
    # compliance/CI gate: non-zero exit if any vessel meets the risk threshold
    if args.command == "locate" and getattr(args, "fail_on", None):
        order = {"low": 1, "medium": 2, "high": 3}
        threshold = order[args.fail_on]
        worst = max((order.get(v["tier"].lower(), 0) for v in result["watchlist"]), default=0)
        if worst >= threshold:
            print(f"FAIL: a vessel meets/exceeds risk tier '{args.fail_on}'", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
