#!/usr/bin/env bash
# Edge / air-gap OFAC SDN feed demo for MARITIMEINT.
#
# Shows the disconnected workflow: list the relevant feed, serve the OFAC SDN
# list from cache OFFLINE, derive the sanctioned-vessel screening list, and
# flag a tracked vessel — all with zero network.
set -euo pipefail
cd "$(dirname "$0")/.."

# Use the committed offline fixture cache so the demo runs with no network.
export COGNIS_FEEDS_CACHE="$PWD/tests/fixtures/feeds_cache"

echo "== relevant edge feeds (cache freshness) =="
python -m maritimeint feeds list

echo
echo "== OFAC SDN designated vessels, served OFFLINE from the edge cache =="
python -m maritimeint import-ofac --from-feed --offline --out /tmp/ofac.json

echo
echo "== screen tracked AIS contacts against the edge-cached OFAC list (offline) =="
python -m maritimeint locate demos/ais_sample.json --sanctions /tmp/ofac.json

# Air-gap transfer: snapshot the cache on a connected box, sneakernet it in:
#   python -m maritimeint feeds update ofac-sdn          # connected box
#   python -m maritimeint feeds snapshot-export feeds.tar.gz
#   python -m maritimeint feeds snapshot-import feeds.tar.gz   # inside the air gap
