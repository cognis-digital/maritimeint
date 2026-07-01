"""Fleet & network analytics for MARITIMEINT.

Where :mod:`maritimeint.core` and :mod:`maritimeint.encounters` score vessels and
*pairs* of vessels, this module reasons about the **whole fleet as a network**: who
meets whom, which vessels cluster into a coordinated ring, and where reported
identity (name, flag/MID) is inconsistent in ways that signal identity laundering.

All pure standard library; every detector returns plain dicts/lists that serialise
straight to JSON and flow through the existing :mod:`maritimeint.intel` exporters.

Detectors / builders
--------------------
* **contact_network** — an undirected graph whose nodes are vessels (MMSIs) and
  whose edges are physical interactions (rendezvous, dark-rendezvous, close-quarters,
  shadowing, convoy co-membership). Edges carry the interaction type(s) and a weight.
* **fleet_rings** — connected components of the contact network with >= 2 members: a
  cluster of vessels that repeatedly interact is a candidate coordinated fleet /
  grey-fleet ring. Ranked by size, edge count, and worst interaction severity.
* **flag_hopping** — a *hull* (keyed by IMO when available, else by reported name)
  seen broadcasting MMSIs from different flag states (MID country codes) over time.
  Re-flagging to obscure ownership is a documented sanctions-evasion tell.
* **identity_rings** — the inverse: a single reported *name* claimed by several
  distinct MMSIs (name cloning), or one MMSI carrying several names (already flagged
  as a single-vessel conflict by core, here elevated to the fleet view).

Defensive framing
-----------------
This is link analysis for maritime-domain awareness and sanctions compliance:
surfacing coordination and identity manipulation an analyst would otherwise have to
assemble by hand. It describes relationships in historical AIS; it is not targeting,
tasking, or interdiction guidance.
"""

from __future__ import annotations

from typing import Any

from .core import (
    AISMessage,
    _by_vessel,
    detect_rendezvous,
    detect_dark_rendezvous,
)
from .encounters import detect_close_quarters, detect_shadowing, detect_convoy


# --------------------------------------------------------------------------- #
# MMSI / MID country decoding
# --------------------------------------------------------------------------- #
# Maritime Identification Digits: the first three digits of an MMSI encode the
# administration (flag state). A partial, offline table of the ranges that recur
# in grey-fleet / sanctions reporting; unknown MIDs fall back to "MID-<nnn>" so
# flag-hopping is still detectable structurally even without a name in the table.
_MID: dict[str, str] = {
    "201": "Albania", "205": "Belgium", "209": "Cyprus", "210": "Cyprus",
    "212": "Cyprus", "232": "United Kingdom", "233": "United Kingdom",
    "234": "United Kingdom", "235": "United Kingdom", "244": "Netherlands",
    "245": "Netherlands", "246": "Netherlands", "247": "Italy",
    "255": "Portugal (Madeira)", "256": "Malta", "248": "Malta", "249": "Malta",
    "256 ": "Malta", "271": "Turkey", "272": "Ukraine", "273": "Russia",
    "304": "Antigua & Barbuda", "305": "Antigua & Barbuda", "308": "Bahamas",
    "309": "Bahamas", "311": "Bahamas", "351": "Panama", "352": "Panama",
    "353": "Panama", "354": "Panama", "355": "Panama", "356": "Panama",
    "357": "Panama", "370": "Panama", "371": "Panama", "372": "Panama",
    "373": "Panama", "374": "Panama", "412": "China", "413": "China",
    "414": "China", "422": "Iran", "431": "Japan", "432": "Japan",
    "440": "South Korea", "441": "South Korea", "445": "North Korea",
    "477": "Hong Kong", "538": "Marshall Islands", "563": "Singapore",
    "564": "Singapore", "565": "Singapore", "566": "Singapore",
    "620": "Comoros", "667": "Sierra Leone", "670": "Togo", "671": "Togo",
    "636": "Liberia", "637": "Liberia", "338": "United States",
    "366": "United States", "367": "United States", "368": "United States",
    "369": "United States",
}


def mid_of(mmsi: str) -> str:
    """First three digits of an MMSI (the Maritime Identification Digits)."""
    digits = "".join(c for c in str(mmsi) if c.isdigit())
    return digits[:3] if len(digits) >= 3 else ""


def flag_of(mmsi: str) -> str:
    """Best-effort flag-state name for an MMSI, else ``MID-<nnn>`` / ``unknown``."""
    mid = mid_of(mmsi)
    if not mid:
        return "unknown"
    return _MID.get(mid, f"MID-{mid}")


# --------------------------------------------------------------------------- #
# contact network
# --------------------------------------------------------------------------- #
_SEV_RANK = {"low": 1, "medium": 2, "high": 3}
_INTERACTIONS = ("rendezvous", "dark_rendezvous", "close_quarters",
                 "shadowing", "convoy")


def _edge_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _pairs_from_finding(f: dict[str, Any]) -> list[tuple[str, str]]:
    """Every unordered vessel pair a multi-vessel finding implies."""
    vessels = list(dict.fromkeys(f.get("vessels", [])))  # dedup, keep order
    pairs = []
    for i in range(len(vessels)):
        for j in range(i + 1, len(vessels)):
            pairs.append(_edge_key(vessels[i], vessels[j]))
    return pairs


def contact_network(msgs: list[AISMessage], **kw: Any) -> dict[str, Any]:
    """Build the vessel-interaction graph.

    Returns ``{"nodes": [...], "edges": [...]}``. Each node is
    ``{"mmsi", "name", "flag", "degree"}``; each edge is
    ``{"vessels": [a, b], "interactions": [...], "weight", "severity"}`` where
    weight is the count of interaction findings joining the pair and severity is the
    worst severity across them. Tunables pass through to the underlying detectors.
    """
    tracks = _by_vessel(msgs)
    findings: list[dict[str, Any]] = []
    findings += detect_rendezvous(
        msgs,
        proximity_nm=kw.get("rendezvous_nm", 0.5),
        min_minutes=kw.get("rendezvous_min_minutes", 30.0),
    )
    findings += detect_dark_rendezvous(
        msgs,
        gap_hours=kw.get("gap_hours", 6.0),
        proximity_nm=kw.get("dark_rendezvous_nm", 5.0),
    )
    findings += detect_close_quarters(
        msgs,
        cpa_nm=kw.get("cpa_nm", 0.5),
        tcpa_max_minutes=kw.get("tcpa_max_minutes", 30.0),
    )
    findings += detect_shadowing(
        msgs,
        standoff_max_nm=kw.get("standoff_max_nm", 8.0),
        min_minutes=kw.get("shadow_min_minutes", 90.0),
    )
    findings += detect_convoy(
        msgs,
        cluster_nm=kw.get("cluster_nm", 3.0),
        min_vessels=kw.get("convoy_min_vessels", 3),
    )

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for f in findings:
        t = f.get("type")
        sev = f.get("severity", "low")
        for pair in _pairs_from_finding(f):
            e = edges.setdefault(pair, {"vessels": list(pair),
                                        "interactions": {}, "worst": "low"})
            e["interactions"][t] = e["interactions"].get(t, 0) + 1
            if _SEV_RANK.get(sev, 0) > _SEV_RANK.get(e["worst"], 0):
                e["worst"] = sev

    degree: dict[str, int] = {}
    edge_list: list[dict[str, Any]] = []
    for pair, e in sorted(edges.items()):
        weight = sum(e["interactions"].values())
        for v in pair:
            degree[v] = degree.get(v, 0) + 1
        edge_list.append({
            "vessels": e["vessels"],
            "interactions": sorted(e["interactions"]),
            "interaction_counts": dict(sorted(e["interactions"].items())),
            "weight": weight,
            "severity": e["worst"],
        })

    nodes = [{
        "mmsi": mmsi,
        "name": track[0].name,
        "flag": flag_of(mmsi),
        "degree": degree.get(mmsi, 0),
    } for mmsi, track in sorted(tracks.items())]

    return {"type": "contact_network", "nodes": nodes, "edges": edge_list}


# --------------------------------------------------------------------------- #
# fleet rings — connected components of the contact network
# --------------------------------------------------------------------------- #
def fleet_rings(msgs: list[AISMessage], min_size: int = 2, **kw: Any) -> list[dict[str, Any]]:
    """Connected components of the contact graph with >= ``min_size`` vessels.

    A group of vessels that repeatedly interact (meet, go dark together, run in a
    convoy, shadow one another) forms a component here — a candidate coordinated
    fleet / grey-fleet ring worth a single analyst look rather than N isolated
    tracks. Ranked by member count, then edges, then worst interaction severity.
    """
    net = contact_network(msgs, **kw)
    adj: dict[str, set[str]] = {n["mmsi"]: set() for n in net["nodes"]}
    edge_index: dict[tuple[str, str], dict[str, Any]] = {}
    for e in net["edges"]:
        a, b = e["vessels"]
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
        edge_index[_edge_key(a, b)] = e
    name_of = {n["mmsi"]: n["name"] for n in net["nodes"]}
    flag_of_node = {n["mmsi"]: n["flag"] for n in net["nodes"]}

    seen: set[str] = set()
    rings: list[dict[str, Any]] = []
    for start in adj:
        if start in seen or not adj[start]:
            continue
        # BFS component
        comp: set[str] = set()
        stack = [start]
        while stack:
            v = stack.pop()
            if v in comp:
                continue
            comp.add(v)
            stack.extend(adj[v] - comp)
        seen |= comp
        if len(comp) < min_size:
            continue
        members = sorted(comp)
        ring_edges = [edge_index[_edge_key(a, b)]
                      for i, a in enumerate(members)
                      for b in members[i + 1:]
                      if _edge_key(a, b) in edge_index]
        worst = "low"
        for e in ring_edges:
            if _SEV_RANK.get(e["severity"], 0) > _SEV_RANK.get(worst, 0):
                worst = e["severity"]
        inter = sorted({i for e in ring_edges for i in e["interactions"]})
        flags = sorted({flag_of_node.get(m, "unknown") for m in members})
        rings.append({
            "type": "fleet_ring",
            "vessels": members,
            "names": {m: name_of.get(m, "") for m in members},
            "flags": flags,
            "vessel_count": len(members),
            "edge_count": len(ring_edges),
            "interactions": inter,
            "multi_flag": len(flags) > 1,
            "severity": worst,
        })
    rings.sort(key=lambda r: (r["vessel_count"], r["edge_count"],
                              _SEV_RANK.get(r["severity"], 0)), reverse=True)
    return rings


# --------------------------------------------------------------------------- #
# flag hopping — a hull broadcasting from different flag states
# --------------------------------------------------------------------------- #
def flag_hopping(
    msgs: list[AISMessage],
    static: dict[str, dict] | None = None,
) -> list[dict[str, Any]]:
    """Detect a single hull associated with MMSIs from *different* flag states.

    A hull is keyed by IMO when a ``static`` ``mmsi -> {"imo": ...}`` map supplies
    one (IMO is hull-bound and durable), else by reported vessel name. If the hull's
    MMSIs decode (via MID) to more than one flag state, that is flag-hopping /
    re-flagging — a documented ownership-obfuscation and sanctions-evasion tactic.
    """
    static = static or {}
    tracks = _by_vessel(msgs)
    # hull key -> {mmsi -> flag}
    hulls: dict[str, dict[str, str]] = {}
    hull_label: dict[str, str] = {}
    for mmsi, track in tracks.items():
        imo = str(static.get(mmsi, {}).get("imo", "")).strip()
        name = next((m.name for m in track if m.name), "")
        if imo:
            key, label = f"imo:{imo}", f"IMO {imo}"
        elif name:
            key, label = f"name:{name.upper()}", name
        else:
            continue  # nothing durable to tie MMSIs together
        hulls.setdefault(key, {})[mmsi] = flag_of(mmsi)
        hull_label[key] = label

    findings: list[dict[str, Any]] = []
    for key, mmsi_flag in hulls.items():
        flags = set(mmsi_flag.values())
        if len(mmsi_flag) >= 2 and len(flags) >= 2:
            findings.append({
                "type": "flag_hopping",
                "hull": hull_label[key],
                "vessels": sorted(mmsi_flag),
                "mmsi_flags": dict(sorted(mmsi_flag.items())),
                "flags": sorted(flags),
                "flag_count": len(flags),
                "severity": "high" if len(flags) >= 3 else "medium",
            })
    findings.sort(key=lambda f: f["flag_count"], reverse=True)
    return findings


# --------------------------------------------------------------------------- #
# identity rings — name cloning across MMSIs
# --------------------------------------------------------------------------- #
def identity_rings(msgs: list[AISMessage]) -> list[dict[str, Any]]:
    """Detect reported-identity manipulation across the fleet.

    * **name_clone** — one reported vessel *name* broadcast by two or more distinct
      MMSIs (spoofing a legitimate vessel's identity, or a serial re-registration).
    * **mmsi_multiname** — one MMSI reporting two or more distinct names over the
      window (elevated from the per-vessel conflict to the fleet identity view).
    """
    tracks = _by_vessel(msgs)
    # name -> set of mmsis
    by_name: dict[str, set[str]] = {}
    findings: list[dict[str, Any]] = []
    for mmsi, track in tracks.items():
        names = sorted({m.name for m in track if m.name})
        for n in names:
            by_name.setdefault(n.upper(), set()).add(mmsi)
        if len(names) >= 2:
            findings.append({
                "type": "mmsi_multiname",
                "mmsi": mmsi,
                "names": names,
                "name_count": len(names),
                "severity": "high",
            })
    for name_up, mmsis in sorted(by_name.items()):
        if len(mmsis) >= 2:
            # recover a display name from the first track carrying it
            display = name_up
            for mmsi in tracks:
                for m in tracks[mmsi]:
                    if m.name and m.name.upper() == name_up:
                        display = m.name
                        break
            findings.append({
                "type": "name_clone",
                "name": display,
                "vessels": sorted(mmsis),
                "mmsi_count": len(mmsis),
                "flags": sorted({flag_of(m) for m in mmsis}),
                "severity": "high",
            })
    findings.sort(key=lambda f: f.get("mmsi_count", f.get("name_count", 0)),
                  reverse=True)
    return findings


def analyze_fleet(
    msgs: list[AISMessage],
    static: dict[str, dict] | None = None,
    **kw: Any,
) -> dict[str, Any]:
    """Run the fleet/network layer and return a combined report.

    Mirrors the :func:`maritimeint.core.analyze` shape so it drops into the same
    exporters and CLI emitters.
    """
    net = contact_network(msgs, **kw)
    rings = fleet_rings(msgs, min_size=kw.get("ring_min_size", 2), **kw)
    hops = flag_hopping(msgs, static=static)
    ids = identity_rings(msgs)
    findings = rings + hops + ids
    zones = kw.get("zones")
    if zones:
        from .zones import annotate_findings
        annotate_findings(findings, zones)
    return {
        "tool": "maritimeint",
        "mode": "fleet",
        "vessels_tracked": len(_by_vessel(msgs)),
        "messages": len(msgs),
        "network": {"nodes": len(net["nodes"]), "edges": len(net["edges"])},
        "finding_counts": {
            "fleet_ring": len(rings),
            "flag_hopping": len(hops),
            "identity_ring": len(ids),
        },
        "network_graph": net,
        "findings": findings,
    }
