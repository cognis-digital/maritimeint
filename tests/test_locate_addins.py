"""LocateAnything watchlist + composable AI add-ins (availability gating)."""

from __future__ import annotations

import os

from maritimeint import addins
from maritimeint.core import load_messages
from maritimeint.locate import locate
from maritimeint.sanctions import load_sanctions, screen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIS = os.path.join(ROOT, "demos", "ais_sample.json")
SANC = os.path.join(ROOT, "demos", "sanctions_sample.json")


def test_watchlist_prioritizes_sanctioned_dark_ship():
    msgs = load_messages(AIS)
    static = {m.mmsi: {"name": m.name} for m in msgs}
    res = locate(msgs, sanctions=load_sanctions(SANC), static=static)
    wl = res["watchlist"]
    top = wl[0]
    assert top["mmsi"] == "210111000" and top["sanctioned"] and top["tier"] == "HIGH"
    # reasons include the gap + the STS rendezvous + the sanctions hit
    joined = " ".join(top["reasons"]).lower()
    assert "sanctions" in joined and "going dark" in joined and "ship-to-ship" in joined
    # the spoofer is flagged too
    assert any(v["mmsi"] == "210444000" and "spoofing" in " ".join(v["reasons"]) for v in wl)


def test_sanctions_screen_matches_by_mmsi_and_name():
    s = load_sanctions(SANC)
    assert screen("210111000", sanctions=s)            # by mmsi
    assert screen("999", name="NEPTUNE STAR", sanctions=s)  # by name
    assert not screen("000000000", name="UNKNOWN", sanctions=s)


def test_addins_availability_is_gated_by_reachable_backend():
    # stub probe: only the vision-fleet answers
    def probe_stub(url):
        return ["qwen2.5-vl"] if "8773" in url else None
    avail = {a["addin"]: a for a in addins.available(probe_fn=probe_stub)}
    # vision prefers the vision backend; reasoning has no preferred match but falls back
    # to whatever IS reachable (adoption: use the fleet you actually run)
    assert avail["vision"]["enabled"] and avail["vision"]["backend"] == "vision-fleet"
    assert avail["reasoning"]["enabled"] and avail["reasoning"]["base_url"].endswith(":8773")

    # nothing reachable -> all add-ins disabled, nothing raised
    none_avail = addins.available(probe_fn=lambda url: None)
    assert all(not a["enabled"] for a in none_avail)


def test_reasoning_prompt_is_defensive():
    msgs = build = [{"mmsi": "1", "tier": "HIGH", "reasons": ["AIS gap"]}]
    text_msgs = addins.build_vision_messages("http://img", note="test")
    # vision message carries the image + a descriptive (not targeting) instruction
    assert text_msgs[0]["content"][0]["text"].lower().startswith("describe any vessels")
    assert text_msgs[0]["content"][1]["image_url"]["url"] == "http://img"
