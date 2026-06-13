# Changelog

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
