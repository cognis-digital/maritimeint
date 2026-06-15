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


def _emit(obj: Any, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(obj, indent=2))
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

    lt = sub.add_parser("loiter", help="detect loitering / STS staging")
    _add_input(lt)
    lt.add_argument("--radius-nm", type=float, default=2.0)
    lt.add_argument("--min-hours", type=float, default=4.0)

    s = sub.add_parser("spoof", help="detect spoofing / identity conflicts")
    _add_input(s)

    r = sub.add_parser("rendezvous", help="detect vessel-to-vessel meetings")
    _add_input(r)
    r.add_argument("--proximity-nm", type=float, default=0.5)
    r.add_argument("--min-minutes", type=float, default=30.0)
    return parser


def _positive_float(name: str, value: float) -> None:
    """Raise SystemExit(2) with a clear message if value is not positive."""
    if value <= 0:
        print(f"error: --{name} must be a positive number, got {value}",
              file=sys.stderr)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Validate numeric arguments before loading data.
    if args.command == "gaps":
        _positive_float("gap-hours", args.gap_hours)
    elif args.command == "jumps":
        _positive_float("max-speed-kn", args.max_speed_kn)
    elif args.command == "loiter":
        _positive_float("radius-nm", args.radius_nm)
        _positive_float("min-hours", args.min_hours)
    elif args.command == "rendezvous":
        _positive_float("proximity-nm", args.proximity_nm)
        _positive_float("min-minutes", args.min_minutes)

    try:
        msgs = load_messages(args.input)
        if args.command == "analyze":
            result: Any = analyze(msgs)
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
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
