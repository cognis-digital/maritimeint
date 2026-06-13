"""AIS feed fetchers — pull real vessel positions into maritimeint's input format.

The detectors run on AIS records: {mmsi, name, timestamp(ISO), lat, lon, sog, cog}.
This module normalizes a provider's records into that shape and writes a JSON file
ready for `maritimeint analyze` / `locate`.

Adapters:
  file      a downloaded CSV or JSON export from any provider (field-mapped) — offline
  aishub    AISHub Web API (needs a free contributor username) — http://data.aishub.net

Note: real-time feeds (AISHub, aisstream.io) require credentials; this normalizes
whatever you can pull. aisstream.io is a websocket stream — see AISSTREAM_NOTE.
Pure standard library.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

AISSTREAM_NOTE = ("aisstream.io is a websocket stream: connect to wss://stream.aisstream.io/v0/stream "
                  "with your API key + a bounding box, collect PositionReport messages, then pass the "
                  "saved JSON to `fetch-ais --source file`. (Needs an API key + a websocket client.)")

# accepted field aliases (lowercased) -> canonical maritimeint field
_ALIASES = {
    "mmsi": "mmsi", "name": "name", "shipname": "name", "vessel_name": "name",
    "lat": "lat", "latitude": "lat", "lon": "lon", "lng": "lon", "long": "lon", "longitude": "lon",
    "sog": "sog", "speed": "sog", "cog": "cog", "course": "cog", "heading": "cog",
    "timestamp": "timestamp", "time": "timestamp", "basedatetime": "timestamp", "t": "timestamp",
}


def _iso(value) -> str:
    """Normalize a timestamp (unix seconds or string) to ISO-8601 UTC."""
    if value in (None, ""):
        return ""
    try:                                  # unix epoch seconds?
        return datetime.fromtimestamp(int(float(value)), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, OSError):
        return str(value)


def normalize_records(rows) -> list[dict]:
    """Map provider records (dicts) to maritimeint AIS records; drop incomplete ones."""
    out = []
    for row in rows:
        rec = {}
        for k, v in row.items():
            canon = _ALIASES.get(str(k).strip().lower())
            if canon and v not in (None, ""):
                rec[canon] = v
        if not all(k in rec for k in ("mmsi", "lat", "lon")):
            continue
        try:
            rec["lat"] = float(rec["lat"]); rec["lon"] = float(rec["lon"])
        except (ValueError, TypeError):
            continue
        rec["mmsi"] = str(rec["mmsi"]).strip()
        rec["timestamp"] = _iso(rec.get("timestamp"))
        if not rec["timestamp"]:
            continue
        for f in ("sog", "cog"):
            if f in rec:
                try:
                    rec[f] = float(rec[f])
                except (ValueError, TypeError):
                    rec.pop(f)
        out.append(rec)
    return out


def from_file(path: str) -> list[dict]:
    text = open(path, encoding="utf-8").read()
    if path.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(text)))
    else:
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("data", data.get("records", []))
        # AISHub JSON is [[meta], [vessels]]
        if rows and isinstance(rows[0], list):
            rows = rows[-1]
    return normalize_records(rows)


def from_aishub(username: str, *, latmin=-90, latmax=90, lonmin=-180, lonmax=180,
                timeout: float = 60.0) -> list[dict]:
    """Pull a bounding box from the AISHub Web API (requires a contributor username)."""
    q = urllib.parse.urlencode({"username": username, "format": 1, "output": "json",
                                "compress": 0, "latmin": latmin, "latmax": latmax,
                                "lonmin": lonmin, "lonmax": lonmax})
    url = "http://data.aishub.net/ws.php?" + q
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    vessels = data[-1] if isinstance(data, list) and data and isinstance(data[-1], list) else []
    return normalize_records(vessels)


def write_ais(records: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)
