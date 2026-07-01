# Fleet analytics, pattern-of-life & COP export — v1.0

> **Scope.** These are **defensive, OSINT, situational-awareness / sanctions-compliance**
> capabilities. They describe *relationships* between vessels, *identity* inconsistencies,
> and *behaviour over time*, entirely from historical AIS. Nothing here plans an
> intercept, issues a maneuvering order, or performs targeting. Every output is a
> relationship, an identity flag, a scored candidate, or a display marker for an analyst.

This layer adds three things on top of the per-vessel (`core`) and pairwise
(`encounters`) detectors:

1. **Fleet / network analytics** (`maritimeint.fleet`) — who interacts with whom, and
   which vessels cluster into a coordinated ring; plus flag-hopping and identity rings.
2. **Pattern-of-life & correlation** (`maritimeint.patterns`) — going-dark timelines,
   multi-signal ship-to-ship-transfer scoring, and per-vessel behavioural baselines.
3. **New exporters** (`maritimeint.intel`) — Cursor-on-Target (CoT) and KML timeline.

All pure standard library, additive, and wired into dedicated CLI subcommands. Every
finding flows unchanged through the existing GeoJSON / KML / STIX / CSV exporters.

---

## 1. Fleet / network analytics — `maritimeint.fleet`

### Contact network (`network`)

Builds an undirected graph whose **nodes are vessels** and whose **edges are physical
interactions** between two hulls — a rendezvous, dark-rendezvous, close-quarters
encounter, shadowing episode, or convoy co-membership. Each edge carries the
interaction type(s), a weight (interaction count), and the worst severity.

```bash
maritimeint network ais.json                 # table: nodes + edges
maritimeint --format json network ais.json   # {"nodes":[...], "edges":[...]}
```

### Fleet rings (`rings`)

Collapses the contact network into **connected components** with ≥ `--min-size`
members. A cluster of vessels that repeatedly interact is a candidate coordinated /
grey-fleet ring — one analyst look instead of N unrelated tracks. Ranked by member
count, then edge count, then worst severity. `multi_flag` is set when the ring's
members carry more than one flag state.

```bash
maritimeint rings ais.json --min-size 2
```

### Flag-hopping (`flag-hopping`)

An MMSI's first three digits (the **Maritime Identification Digits**, MID) encode the
flag state. `flag_hopping` ties MMSIs to a **hull** — by IMO when a static index
supplies one (IMO is hull-bound and durable), else by reported name — and flags any
hull whose MMSIs decode to **more than one flag state**. Re-flagging to obscure
ownership is a documented sanctions-evasion tactic. An offline MID→flag table covers
the ranges that recur in grey-fleet reporting; unknown MIDs still register as distinct
`MID-nnn` tokens so hopping is detectable structurally.

### Identity rings (`identity`)

The identity-manipulation view: **`name_clone`** (one reported name broadcast by two
or more distinct MMSIs — impersonation or serial re-registration) and
**`mmsi_multiname`** (one MMSI reporting several names).

### Combined (`fleet`)

`maritimeint fleet ais.json` runs rings + flag-hopping + identity rings in one pass
and returns an `analyze()`-shaped report (with the full `network_graph` attached).

---

## 2. Pattern-of-life & correlation — `maritimeint.patterns`

### Going-dark timeline (`gap-timeline`)

Reconstructs each vessel's AIS **dark windows** into an ordered timeline with roll-ups:
how many times it went dark, total dark hours, longest window, and the reappearance
displacement / drift speed per window. A vessel that repeatedly goes dark for long
stretches and reappears far away is a very different risk from one short sensor dropout.

### STS-transfer scoring (`sts`)

A ship-to-ship transfer is rarely one clean event; it is a **stack** of signals.
`sts_transfer_score` anchors on each (dark-)rendezvous and folds in **overlapping**
loitering and going-dark by either party, producing a single **scored, explained**
STS-candidate with an evidence list a reviewer can accept or dismiss. A dark meeting
is a stronger base signal than a broadcast one; each corroborating signal adds to the
score.

### Pattern-of-life (`pattern-of-life`)

Per-vessel behavioural **baseline**: reporting span, active hours-of-day, area of
operation (bounding box + centroid + max extent), speed statistics, and dark/loiter
event counts. This is the reference frame an anomaly is measured against.

`maritimeint patterns ais.json` runs all three in one `analyze()`-shaped report.

---

## 3. New exporters — `maritimeint.intel`

### Cursor-on-Target (`--to cot`)

Renders geolocated findings as **Cursor-on-Target** `<event>` elements under an
`<events>` root — the XML the TAK / ATAK common-operating-picture ecosystem speaks —
so a maritimeint run drops onto a shared COP as track markers.

> **Affiliation is always `a-u-S` (unknown, surface) — never `a-h-` (hostile).**
> A CoT event here carries a position and a label for situational-awareness display;
> it is never a task, a track-to-engage, or an affiliation/targeting judgement.

### KML timeline (`--to kml-timeline`)

Like the KML exporter, but every placemark carries a `<TimeStamp>` / `<TimeSpan>` so
Google Earth's time slider **animates the findings in sequence** — replaying how an
event developed.

```bash
maritimeint export ais.json --to cot          -o findings.cot.xml
maritimeint export ais.json --to kml-timeline -o timeline.kml
```

---

## Try it offline

```bash
PYTHONUTF8=1 python demos/06_fleet_network.py     # contact graph + rings
PYTHONUTF8=1 python demos/07_flag_hopping.py      # re-flagged hulls + name clones
PYTHONUTF8=1 python demos/08_sts_correlation.py   # multi-signal STS scoring
PYTHONUTF8=1 python demos/09_pattern_of_life.py   # per-vessel baselines
PYTHONUTF8=1 python demos/10_cot_cop_export.py    # CoT + KML timeline
```

All run against the bundled offline fixture (no feeds, no keys, no network).
