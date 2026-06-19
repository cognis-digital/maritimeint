# Demo 04 — dark ship-to-ship transfer, zones & port-calls (v0.8)

A worked sanctions-evasion scenario exercising every v0.8 layer.

**Cast**
- `412888001` *GREY TANKER* (IMO 9111111) — sits at **Kharg Island** (a sanctioned
  port), then **goes dark for 10h** off the Iranian coast, reappears, and a week later
  surfaces at **Singapore** (a clean hub) to sell.
- `352000777` *LIGHTER ONE* — keeps broadcasting right where the tanker vanished.
- `636000123-126` — four vessels all pinned to the **exact same position** near
  Bandar Abbas within 15 minutes (a GPS-jamming hotspot).

## Run it

```bash
# full suite, with zones tagging every finding by location
maritimeint --format json analyze demos/04-dark-sts-zones/feed.json \
    --zones demos/04-dark-sts-zones/zones.geojson

# the dark-STS signature on its own
maritimeint dark-rendezvous demos/04-dark-sts-zones/feed.json

# GPS spoofing / jamming
maritimeint gps demos/04-dark-sts-zones/feed.json

# zone entries / exits / dwell
maritimeint zones demos/04-dark-sts-zones/feed.json \
    --zones demos/04-dark-sts-zones/zones.geojson

# port itinerary — Kharg (sanctioned) -> Singapore
maritimeint port-calls demos/04-dark-sts-zones/feed.json --itinerary
```

## What you'll see
- **dark_rendezvous** — GREY TANKER went dark while LIGHTER ONE loitered <2nm away.
- **gps_jamming** — 4 vessels snapped to one synthetic position.
- **port_call / itinerary** — a sanctioned-port call (Kharg) followed by a clean-hub
  call (Singapore): the classic load-dirty / sell-clean leg.
- Every positional finding is tagged with the **zone** it falls in (Persian Gulf EEZ,
  Kharg Island Terminal).
