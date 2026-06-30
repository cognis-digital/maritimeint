"""Shared helpers for the maritimeint demo scenarios.

Every scenario loads the same bundled, offline AIS fixture
(``demos/data/gulf_scenario.json``) and runs the *real* public API
(``maritimeint.core`` / ``locate`` / ``zones`` / ``ports`` / ``intel`` /
``encounters``) — no live feeds, no API keys, no network. The fixture is a
small synthetic Persian-Gulf picture (7 vessels) hand-built so each detector
has something to find; see ``scripts/gen_gulf_scenario.py``.
"""
from __future__ import annotations

import os
import sys

# allow `python demos/xx.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint.core import load_messages  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO_ROOT, "demos", "data")

SCENARIO = os.path.join(DATA, "gulf_scenario.json")
ZONES = os.path.join(DATA, "gulf_zones.geojson")
SANCTIONS = os.path.join(DATA, "gulf_sanctions.json")


def messages(path: str = SCENARIO):
    """Load the bundled AIS fixture into validated, time-sorted AISMessages."""
    return load_messages(path)


def static_index(msgs) -> dict:
    """mmsi -> {name, imo} map for sanctions screening (mirrors the CLI)."""
    idx: dict[str, dict] = {}
    for m in msgs:
        rec = idx.setdefault(m.mmsi, {"name": m.name, "imo": ""})
        if m.name and not rec["name"]:
            rec["name"] = m.name
    return idx


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def bullet(text: str, indent: int = 5) -> None:
    print(" " * indent + "- " + text)
