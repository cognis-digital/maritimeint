# Changelog

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
