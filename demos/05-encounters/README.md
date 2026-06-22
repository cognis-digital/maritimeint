# Demo 05 — track-interaction signatures (v0.9)

Two contacts on reciprocal courses at the same latitude, closing head-on.

```bash
maritimeint encounters ais.json            # CPA/TCPA close-quarters flagged high
maritimeint analyze ais.json               # folded into the master report
maritimeint export ais.json --to geojson   # drop the encounter onto a map
```

See [`docs/ENCOUNTERS.md`](../../docs/ENCOUNTERS.md) for shadowing, convoy and drift.
