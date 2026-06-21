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


def _load_zones(path: str):
    from .zones import load_zones
    return load_zones(path)


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
    a.add_argument("--zones", default=None, help="zone/geofence GeoJSON to tag findings with location")

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

    dr = sub.add_parser("dark-rendezvous",
                        help="correlate a vessel going dark with another loitering at the spot")
    _add_input(dr)
    dr.add_argument("--gap-hours", type=float, default=6.0)
    dr.add_argument("--proximity-nm", type=float, default=5.0)

    gp = sub.add_parser("gps", help="detect GPS spoofing (circling) / jamming hotspots")
    _add_input(gp)

    z = sub.add_parser("zones", help="detect zone/geofence entries, exits and dwell")
    _add_input(z)
    z.add_argument("--zones", required=True, help="zone GeoJSON / native zone list")

    pc = sub.add_parser("port-calls", help="infer port calls + sequence itineraries (risk-tagged)")
    _add_input(pc)
    pc.add_argument("--ports", default=None, help="custom port registry JSON (else built-in)")
    pc.add_argument("--min-dwell-hours", type=float, default=1.0)
    pc.add_argument("--itinerary", action="store_true", help="sequence calls into per-vessel itineraries")

    lo = sub.add_parser("locate", help="prioritized + explained grey-fleet watchlist")
    _add_input(lo)
    lo.add_argument("--sanctions", default=None, help="sanctions list JSON to cross-reference")
    lo.add_argument("--zones", default=None, help="zone/geofence GeoJSON to tag findings with location")
    lo.add_argument("--ai", action="store_true",
                    help="augment with the reasoning add-in if a model backend is reachable")
    lo.add_argument("--endpoint", default=None,
                    help="OpenAI-compatible base URL for add-ins (e.g. a live edgemesh gateway)")
    lo.add_argument("--model", default=None, help="model id for the add-in")
    lo.add_argument("--fail-on", choices=["low", "medium", "high"], default=None,
                    help="exit non-zero if any vessel is at/above this tier (compliance/CI gate)")
    lo.add_argument("--emit", default=None,
                    choices=["stix", "misp", "sigma", "splunk", "elastic", "slack", "discord", "webhook"],
                    help="forward the watchlist to a platform via cognis-connect")
    lo.add_argument("--emit-url", default=None, help="destination URL for --emit (HEC/webhook/MISP)")
    lo.add_argument("--emit-token", default=None, help="auth token for --emit")
    lo.add_argument("--emit-dry-run", action="store_true", help="preview the --emit request, don't send")

    vi = sub.add_parser("vision", help="triage maritime imagery for vessel presence (VL add-in)")
    vi.add_argument("image", help="image URL or data URI (e.g. a Sentinel-1/optical scene)")
    vi.add_argument("--endpoint", default=None, help="OpenAI-compatible VL base URL (live edgemesh gateway)")
    vi.add_argument("--model", default=None)
    vi.add_argument("--note", default="", help="optional context for the triage")

    ex = sub.add_parser("export",
                        help="run analysis and export findings as GeoJSON / KML / STIX 2.1 / CSV")
    _add_input(ex)
    ex.add_argument("--to", choices=["geojson", "kml", "stix", "csv"], default="geojson",
                    help="export format (default: geojson)")
    ex.add_argument("--zones", default=None, help="zone GeoJSON to tag findings with location")
    ex.add_argument("-o", "--output", default=None, help="write to file instead of stdout")

    sub.add_parser("menu", help="interactive multi-level menu")
    sub.add_parser("addins", help="show available AI add-ins (VL + reasoning) and their backends")

    io = sub.add_parser("import-ofac", help="fetch the live OFAC SDN list -> a --sanctions JSON of designated vessels")
    io.add_argument("--out", default="ofac_sanctions.json", help="output sanctions JSON path")
    io.add_argument("--from-file", default=None, help="parse a local SDN.csv instead of fetching")
    io.add_argument("--url", default=None, help="override the SDN.csv URL")

    isn = sub.add_parser("import-sanctions", help="import sanctioned vessels from OFAC / UK OFSI / EU / OpenSanctions (merge with 'all')")
    isn.add_argument("--source", choices=["ofac", "ofsi", "eu", "opensanctions", "all"], default="all")
    isn.add_argument("--from-file", default=None, help="parse a downloaded list file instead of fetching")
    isn.add_argument("--out", default="sanctions.json")

    fa = sub.add_parser("fetch-ais", help="fetch/normalize AIS positions into analyze/locate input")
    fa.add_argument("--source", choices=["file", "aishub"], default="file")
    fa.add_argument("--from-file", default=None, help="a provider CSV/JSON export to normalize")
    fa.add_argument("--username", default=None, help="AISHub contributor username")
    fa.add_argument("--out", default="ais.json")
    fa.add_argument("--latmin", type=float, default=-90); fa.add_argument("--latmax", type=float, default=90)
    fa.add_argument("--lonmin", type=float, default=-180); fa.add_argument("--lonmax", type=float, default=180)
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
    if args.command == "import-sanctions":
        from . import ofac, sanctions_sources as ss
        try:
            if args.from_file:
                with open(args.from_file, encoding="utf-8") as fh:
                    src = "opensanctions" if args.source == "all" else args.source
                    entries = ss.parse(src, fh.read())
            elif args.source == "all":
                # merge every source with a default feed (OFAC + OpenSanctions)
                fetched = []
                for s in ("ofac", "opensanctions"):
                    try:
                        fetched.append(ss.parse(s, ss.fetch(s)))
                    except Exception as exc:  # one feed down shouldn't kill the merge
                        print(f"  ({s}: skipped - {exc})", file=sys.stderr)
                entries = ss.merge(*fetched)
            else:
                entries = ss.parse(args.source, ss.fetch(args.source))
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        ofac.write_sanctions(entries, args.out)
        with_imo = sum(1 for e in entries if e.get("imo"))
        print(f"wrote {len(entries)} sanctioned vessels ({with_imo} with IMO) from {args.source} to {args.out}")
        print(f"use it:  maritimeint locate <ais.json> --sanctions {args.out}")
        return 0
    if args.command == "fetch-ais":
        from . import ais_fetch as af
        try:
            if args.source == "file":
                if not args.from_file:
                    print("error: --source file needs --from-file <provider export>", file=sys.stderr)
                    return 1
                records = af.from_file(args.from_file)
            else:  # aishub
                if not args.username:
                    print("error: --source aishub needs --username (free AISHub contributor account)", file=sys.stderr)
                    print(af.AISSTREAM_NOTE, file=sys.stderr)
                    return 1
                records = af.from_aishub(args.username, latmin=args.latmin, latmax=args.latmax,
                                         lonmin=args.lonmin, lonmax=args.lonmax)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        af.write_ais(records, args.out)
        print(f"wrote {len(records)} AIS records to {args.out}")
        print(f"use it:  maritimeint analyze {args.out}")
        return 0

    try:
        msgs = load_messages(args.input)
        if args.command == "export":
            from . import intel
            zones = _load_zones(args.zones) if getattr(args, "zones", None) else None
            analysis = analyze(msgs, zones=zones) if zones else analyze(msgs)
            text = intel.export(analysis, args.to)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as fh:
                    fh.write(text if text.endswith("\n") else text + "\n")
                print(f"wrote {args.to} export "
                      f"({len(analysis.get('findings', []))} findings) to {args.output}",
                      file=sys.stderr)
            else:
                print(text)
            return 0
        if args.command == "analyze":
            zones = _load_zones(args.zones) if getattr(args, "zones", None) else None
            result: Any = analyze(msgs, zones=zones) if zones else analyze(msgs)
        elif args.command == "locate":
            sanctions = load_sanctions(args.sanctions) if args.sanctions else None
            zones = _load_zones(args.zones) if getattr(args, "zones", None) else None
            static = {m.mmsi: {"name": m.name} for m in msgs}
            result = locate(msgs, sanctions=sanctions, static=static,
                            **({"zones": zones} if zones else {}))
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
        elif args.command == "dark-rendezvous":
            from .core import detect_dark_rendezvous
            result = detect_dark_rendezvous(msgs, gap_hours=args.gap_hours,
                                            proximity_nm=args.proximity_nm)
        elif args.command == "gps":
            from .core import detect_gps_anomalies
            result = detect_gps_anomalies(msgs)
        elif args.command == "zones":
            from .zones import detect_zone_transits
            result = detect_zone_transits(msgs, _load_zones(args.zones))
        elif args.command == "port-calls":
            from .ports import detect_port_calls, sequence_itineraries, load_ports
            ports = load_ports(args.ports) if args.ports else None
            calls = detect_port_calls(msgs, ports=ports, min_dwell_hours=args.min_dwell_hours)
            result = sequence_itineraries(calls) if args.itinerary else calls
        else:  # pragma: no cover
            parser.error(f"unknown command {args.command}")
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _emit(result, args.format)
    # optional: forward the watchlist to a platform via cognis-connect
    if args.command == "locate" and getattr(args, "emit", None):
        from . import connect
        try:
            res = connect.forward(result, args.emit, url=args.emit_url,
                                  token=args.emit_token, dry_run=args.emit_dry_run)
        except (ImportError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(res if isinstance(res, str) else json.dumps(res, indent=2), file=sys.stderr)
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
