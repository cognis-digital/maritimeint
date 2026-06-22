"""Edge / air-gap data-feed ingestion for MARITIMEINT.

Thin wrapper around the bundled, stdlib-only ``datafeeds`` engine (keyless HTTPS
fetch -> disk cache -> offline re-serve -> sneakernet snapshot). It restricts the
shared 17-feed catalog to the feeds that are *relevant to maritime intelligence*
and resolves the OFAC SDN sanctions list through that edge cache so vessel
screening keeps working on disconnected / shipboard / military edge gear.

Relevant feed(s):
  ofac-sdn   US Treasury OFAC SDN list (sanctioned entities, **vessels**, aircraft)
             https://www.treasury.gov/ofac/downloads/sdn.csv

Why through the cache: maritimeint screens AIS contacts against real OFAC
designations. On a connected box ``update`` refreshes the cached SDN.csv; on an
air-gapped box you import a snapshot and every screen runs ``offline=True`` with
zero network. The parsed vessel entries feed straight into ``maritimeint.locate``.

Pure standard library.
"""

from __future__ import annotations

from typing import Any, Optional

from . import datafeeds
from . import ofac

# Catalog ids this tool actually consumes. Keep tight so `feeds list` only
# surfaces the maritime-relevant domain rather than the whole 17-feed catalog.
RELEVANT_FEEDS: tuple[str, ...] = ("ofac-sdn",)


def _catalog() -> dict:
    return datafeeds.load_catalog()


def relevant_catalog() -> dict:
    """The shared catalog filtered to MARITIMEINT's relevant feeds."""
    cat = _catalog()
    feeds = [f for f in cat.get("feeds", []) if f["id"] in RELEVANT_FEEDS]
    return {"feeds": feeds}


def list_feeds() -> list[dict]:
    """Catalog rows for the relevant feeds, with cache freshness."""
    out = []
    for f in relevant_catalog()["feeds"]:
        age = datafeeds.cached_age_hours(f["id"])
        row = dict(f)
        row["cached_age_hours"] = age
        row["cached"] = age is not None
        out.append(row)
    return out


def update(feed_id: str) -> str:
    """Fetch + cache a relevant feed (online). Returns the cache path."""
    _guard(feed_id)
    return str(datafeeds.update(feed_id, catalog=_catalog()))


def get(feed_id: str, *, offline: bool = False) -> Any:
    """Return the cached/fetched feed payload (offline-capable)."""
    _guard(feed_id)
    return datafeeds.get(feed_id, offline=offline, catalog=_catalog())


def _guard(feed_id: str) -> None:
    if feed_id not in RELEVANT_FEEDS:
        raise KeyError(
            f"{feed_id!r} is not a MARITIMEINT-relevant feed; "
            f"choose from {', '.join(RELEVANT_FEEDS)}"
        )


# --------------------------------------------------------------------------- #
# Real enrichment: resolve OFAC sanctioned **vessels** through the edge cache.
# --------------------------------------------------------------------------- #
def sanctioned_vessels(*, offline: bool = False) -> list[dict]:
    """Return maritimeint sanctions entries (designated vessels) sourced from the
    edge-cached OFAC SDN list.

    ``offline=True`` serves the snapshot cache only and never touches the network,
    so this works inside an air gap once a snapshot has been imported.
    """
    text = get("ofac-sdn", offline=offline)
    return ofac.to_sanctions(text)


def snapshot_export(path: str) -> int:
    """Tar the feed cache for sneakernet into an air-gapped enclave."""
    return datafeeds.snapshot_export(path)


def snapshot_import(path: str) -> int:
    """Import a feed-cache snapshot inside an air gap."""
    return datafeeds.snapshot_import(path)
