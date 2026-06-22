# Changelog

## [0.9.0] — 2026-06-22

The "track-interaction & behaviour" release — a new analysis layer
(`maritimeint/encounters.py`) that reasons about how vessel *tracks relate to one
another* and how a single track *behaves over time*, rather than scoring each
vessel in isolation. All pure standard library, additive, folded into `analyze`,
and exported through the existing GeoJSON / KML / STIX 2.1 / CSV pipeline.

Defensive / situational-awareness / OSINT only: every output is a *separation* or a
*pattern label* for an analyst. No intercept planning, maneuvering instructions,
targeting, or fire-control of any kind.

### Added
- **CPA / TCPA close-quarters (`detect_close_quarters`, `close-quarters` command)**
  — Closest Point of Approach distance and Time to CPA between every vessel pair via
  the standard relative-motion model (reported `sog`/`cog`, or derived from
  neighbouring fixes). Flags *converging* tracks projected to pass inside a danger
  radius within a TCPA bound. Diverging or safely-parallel pairs do not trip it.
- **Shadowing (`detect_shadowing`, `shadowing` command)** — one vessel persistently
  trailing another at a held standoff `[min, max]` nm on a matched course over an
  extended window; identifies leader/follower roles. Distinct from `rendezvous`
  (which closes to contact) and `convoy` (a tight abreast cluster).
- **Convoy / co-movement (`detect_convoy`, `convoy` command)** — single-link
  clustering per time-epoch where edges require proximity *and* matched heading *and*
  matched speed; a membership set that re-forms across multiple epochs is a convoy.
  Surfaces escort groups & shepherded flotillas single-vessel detection misses.
- **Drift / not-under-command (`detect_drift`, `drift` command)** — runs of
  near-zero-speed fixes with a wide heading swing → disabled / dragging / possible
  distress. A safety early-warning, not an anomaly-of-intent. Catches unreported
  `sog` via displacement.
- **`encounters` command + `analyze_encounters`** — runs all four in one pass; also
  folded into `core.analyze` so the new findings appear in `finding_counts`, score
  the per-vessel risk ranking, and flow through every exporter unchanged.
- **Docs** — `docs/ENCOUNTERS.md` (use-case walkthrough, frank threat/defensive
  framing, tuning table, candid limitations) + a generated `docs/encounters.svg`
  diagram (CC0, no third-party assets) + `demos/05-encounters`.
- **Tests** — `tests/test_encounters.py`: 77 new offline tests covering each detector,
  edge/negative cases, CPA math, `analyze` integration, exporters, and CLI.

## [0.8.0] — 2026-06-19

The "spatial context + dark STS" release — four new detection layers that answer
*where* an event happened and catch the evasion patterns the v0.7 detectors missed.
All additive, standard-library, and folded into `analyze` / `locate`.

### Added
- **Zone intelligence (`maritimeint/zones.py`)** — define named areas (EEZs,
  sanctioned ports, exclusion / war-risk zones) as GeoJSON or the native zone form;
  `zones` command reports entry/exit + dwell, and `--zones` on `analyze`/`locate`
  tags every finding with the zone(s) it falls in. Ray-casting point-in-polygon and
  great-circle "circle" zones, zero deps.
- **Dark-rendezvous correlation (`detect_dark_rendezvous`)** — the real dark-STS
  signature: when one vessel switches off AIS, find the vessel still broadcasting at
  the spot. `rendezvous` needs both parties live; this catches the one that goes dark.
  New `dark-rendezvous` command.
- **GPS spoofing / jamming (`detect_gps_anomalies`)** — `circle_spoof` (a track
  populating the whole compass around a tight centroid — the "circling" artifact of
  GPS spoofing near conflict zones) and `gps_jamming` (many distinct vessels pinned
  to one synthetic position). New `gps` command.
- **Port-call sequencing (`maritimeint/ports.py`)** — infer dwell-based port calls
  from a built-in (or custom) port registry, sequence each vessel's itinerary, and
  flag calls at sanctioned / high-risk ports and the legs between them. New
  `port-calls` command (`--itinerary`, `--ports`).
- 19 new tests (61 total).

## [0.7.0] — 2026-06-13

The "ships to your SOC" release — the watchlist now forwards to any platform via the
new suite-wide [`cognis-connect`](https://github.com/cognis-digital/cognis-connect) SDK.

### Added
- **`locate --emit {stix,misp,sigma,splunk,elastic,slack,discord,webhook}`** — maps each
  flagged vessel to a canonical `Finding` (sanctioned -> critical) and forwards it:
  STIX 2.1 / MISP / Sigma / Splunk HEC / Elastic `_bulk` / Slack / Discord / webhook.
  `--emit-url`, `--emit-token`, `--emit-dry-run` (preview the exact request, send nothing).
- `maritimeint/connect.py` — the watchlist->Finding bridge. cognis-connect is a **soft
  dependency** (`pip install "cognis-maritimeint[connect]"`); `--emit` reports how to get
  it if absent and the core is unaffected.
- Tests for the mapping + STIX bundle + a dry-run Slack CLI round-trip (42 total).

## [0.6.0] — 2026-06-13

The "every list, any feed" release — pull sanctioned-vessel designations from the four
major public sources and normalize live AIS into the detectors, all standard-library.

### Added
- **Multi-source sanctions importer** (`maritimeint/sanctions_sources.py`) — adapters
  for the real published formats of each major designation list, normalized into one
  `--sanctions` shape:
  - **OFAC** SDN.csv (via `maritimeint.ofac`)
  - **UK OFSI** consolidated list CSV — keeps `Group Type = Ship` rows, pulls the IMO
  - **EU** consolidated list XML — vessel subject-type entities + IMO identification
  - **OpenSanctions** Follow-the-Money JSONL — `schema == "Vessel"` (aggregates
    OFAC/EU/UK/UN; the most reliable single multi-source feed)
- **`merge()`** — combines sources and de-duplicates by IMO → MMSI → normalized name,
  *unioning* the source/program so you can see every list a vessel sits on (and an MMSI
  from one feed fills the gap where another had only an IMO).
- **`import-sanctions --source {ofac,ofsi,eu,opensanctions,all}`** — `all` fetches +
  merges every feed with a public endpoint (OFAC + OpenSanctions); any source accepts
  `--from-file` for a list you downloaded (OFSI/EU endpoints drift / gate their service).
- **Live AIS fetcher** (`maritimeint/ais_fetch.py`) + **`fetch-ais`** — normalizes any
  provider's CSV/JSON export (field-aliased, unix-time → ISO UTC) into analyze/locate
  input; `--source aishub --username …` pulls a bounding box from the AISHub Web API.
  aisstream.io websocket guidance documented inline (`AISSTREAM_NOTE`).
- Fixtures + tests for OFSI/EU/OpenSanctions parsing, cross-source merge, and AIS
  normalization, plus CLI round-trips that feed `locate`/`analyze` (39 total).
- **Interop expansion** — `INTEROP.md` gains copy-paste **tool-chaining recipes**
  (sanctions screen → ownership/finance pivot → GEOINT → STIX/ATT&CK export →
  cognition/agents → counter-UAS fusion) and **seven named reference stacks** across the
  300+ suite. New **`examples/interop_demo.py`** runs a live chain offline from bundled
  fixtures: maritimeint → humind → agentlex (`escalate/1` Horn rule) → edgemesh brief,
  each hop degrading gracefully when a sibling repo / model backend is absent.

## [0.5.0] — 2026-06-13

### Added
- **OFAC SDN importer** (`maritimeint/ofac.py`) + **`import-ofac`** — fetch the live
  Treasury SDN.csv (or parse a local copy), keep `vessel` records, extract IMO/MMSI from
  the remarks, and write a `--sanctions` JSON usable directly by `locate`. Offline
  fixture `demos/ofac_sdn_sample.csv` + integration test (NEPTUNE STAR → flagged).

## [0.4.0] — 2026-06-13

The "adoption" release — works with real data and whatever backend you run, and drops
into a compliance pipeline.

### Added
- **CSV AIS ingest** — `load_messages` now reads CSV (the common AIS-provider export
  format), not just JSON; empty cells are treated as absent. Demo: `demos/ais_sample.csv`.
- **`--fail-on {low,medium,high}` compliance gate** — `locate` exits non-zero if any
  vessel meets/exceeds the tier, so it slots straight into a screening/CI pipeline.
- **Backend works with any fleet** — `MARITIMEINT_ENDPOINT` / `OPENAI_BASE_URL` env
  override, plus auto-discovery across the common local OpenAI-compatible ports, so a
  local fleet *under any name* (or Ollama/vLLM/LM Studio/edgemesh/…) is found
  automatically. Add-ins fall back to whatever backend is actually reachable.
- Tests for CSV ingest, the fail-on gate, and any-port discovery (25 total).

## [0.3.0] — 2026-06-13
### Added
- **Live-endpoint add-ins**: `locate --endpoint <url> --model <id>` and a new
  `vision <image> --endpoint <url>` command point the reasoning/vision add-ins at any
  OpenAI-compatible `/v1` — a **live edgemesh gateway** (which unifies the Cognis fleet)
  or a fleet backend directly. Discovery still auto-finds local backends when no
  `--endpoint` is given.
- **`vision` command** — triage maritime imagery (e.g. a Sentinel-1/optical scene) for
  vessel presence/characteristics via a VL model. Descriptive situational-awareness only.
- End-to-end integration tests against a live mock `/v1` server proving the reasoning +
  vision wiring (and graceful failure when no backend) — 21 tests total.

## [0.2.0] — 2026-06-13

The "LocateAnything + AI add-ins" release — from a detector suite to a usable
grey-fleet intelligence tool for the maritime industrial complex (sanctions
compliance, P&I/marine insurance, port state control, maritime security).

### Added
- **`locate` — the LocateAnything watchlist runtime** (`maritimeint/locate.py`):
  one call runs the full detector suite, folds in sanctions screening, and returns a
  **prioritized, explained watchlist** — each vessel with a tier (HIGH/MEDIUM/LOW), a
  composite score, and plain-language reasons (going dark, STS rendezvous, spoofing,
  sanctions hit). `maritimeint locate <ais.json> [--sanctions list.json] [--ai]`.
- **Sanctions cross-reference** (`maritimeint/sanctions.py`): match tracked vessels to
  an OFAC SDN / EU / UK OFSI-style list by **MMSI / IMO / name** (IMO is the durable,
  hull-bound key). Includes a clearly-labeled synthetic sample list.
- **Composable AI add-ins** (`maritimeint/addins.py`): optional **vision** (maritime
  imagery triage / dark-vessel situational awareness) and **reasoning** (narrative risk
  assessment of the watchlist) that **stack** onto the stdlib core via an
  OpenAI-compatible backend — an **edgemesh** gateway or the Cognis fleet
  (`uncensored-fleet`, `cognis-code`, vision/VL). **Hardware/availability-gated:** if no
  backend is reachable, add-ins stay off and the core still runs. `maritimeint addins`.
- **Multi-level interactive menu** (`maritimeint/menu.py`, `maritimeint menu`).
- A **realistic demo** (`demos/ais_sample.json`): a dark-ship scenario (AIS gap → STS
  rendezvous → spoof jump) that exercises every detector.
- Tests for locate / sanctions / add-in availability gating (17 total).

### Scope
Strictly maritime-domain *awareness* — detection, identification, risk analysis. No
targeting, interdiction, or engagement. The sanctions sample is synthetic, not a real
designation.

## [0.1.0]
- Initial AIS analysis engine: gaps, speed-jumps, loitering, spoofing, rendezvous,
  risk ranking; CLI; MCP server; polyglot ports.
