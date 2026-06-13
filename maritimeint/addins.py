"""Composable AI add-ins for MARITIMEINT — optional VL + reasoning augmentation.

The detection core is pure stdlib and always works. Add-ins **stack** extra
capability on top *when an OpenAI-compatible model backend is reachable* — the
Cognis fleet (`uncensored-fleet`, `cognis-code`, vision/VL) or an **edgemesh**
gateway that unifies them behind one endpoint. Availability is hardware/deployment
limited: if a backend isn't up, that add-in is simply disabled and nothing breaks.

Two add-ins ship:
  - **reasoning** — turn the watchlist into a narrative analyst assessment
    (prioritization + rationale). Prefers a reasoning/uncensored model.
  - **vision** — triage maritime imagery for vessel presence/characteristics
    (dark-vessel situational awareness). Prefers a vision-language model.

Both are strictly analytical/defensive (describe & prioritize); no targeting.
Pure standard library (urllib).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable

# Set MARITIMEINT_ENDPOINT (or OPENAI_BASE_URL) to point every add-in at YOUR backend —
# a local fleet under any name, an edgemesh gateway, Ollama, vLLM, LM Studio, etc.
ENV_ENDPOINT = os.environ.get("MARITIMEINT_ENDPOINT") or os.environ.get("OPENAI_BASE_URL")

# Named Cognis / edgemesh backends probed by default...
BACKENDS: dict[str, str] = {
    "edgemesh": "http://127.0.0.1:8780",          # unifies the whole fleet behind one /v1
    "uncensored-fleet": "http://127.0.0.1:8774",
    "cognis-code": "http://127.0.0.1:11434",
    "vision-fleet": "http://127.0.0.1:8773",
}
# ...plus common local OpenAI-compatible ports, so a fleet "named something else"
# (Ollama, vLLM, LM Studio, SGLang, Jan, llama.cpp, text-gen-webui, KoboldCpp, …) is
# still auto-found. Discovery is whatever answers GET /v1/models on localhost.
COMMON_PORTS: list[int] = [8780, 11434, 8000, 8080, 1234, 1337, 30000, 5000, 5001, 8773, 8774, 8772]

# add-in key -> (capability, preferred backends in priority order)
ADDINS: dict[str, dict] = {
    "reasoning": {"capability": "narrative risk assessment of the watchlist",
                  "prefers": ["edgemesh", "uncensored-fleet", "cognis-code"]},
    "vision": {"capability": "maritime imagery triage (dark-vessel situational awareness)",
               "prefers": ["edgemesh", "vision-fleet"]},
}


def probe(base_url: str, timeout: float = 2.0) -> list[str] | None:
    """Return model ids a backend serves, or None if unreachable."""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/v1/models", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    items = data.get("data", data) if isinstance(data, dict) else data
    out = []
    for it in items if isinstance(items, list) else []:
        mid = it.get("id") if isinstance(it, dict) else it
        if isinstance(mid, str):
            out.append(mid)
    return out


def discover(probe_fn: Callable[[str], list[str] | None] = probe) -> dict[str, tuple[str, list[str]]]:
    """Find reachable OpenAI-compatible backends: env override, named, then common ports.

    Returns {label: (base_url, models)}. The env endpoint (your fleet, any name) wins.
    """
    found: dict[str, tuple[str, list[str]]] = {}
    if ENV_ENDPOINT:
        m = probe_fn(ENV_ENDPOINT)
        if m is not None:
            found["env"] = (ENV_ENDPOINT, m)
    for name, url in BACKENDS.items():
        m = probe_fn(url)
        if m is not None:
            found[name] = (url, m)
    for port in COMMON_PORTS:
        url = f"http://127.0.0.1:{port}"
        if url in (v[0] for v in found.values()):
            continue
        m = probe_fn(url)
        if m is not None:
            found[f"localhost:{port}"] = (url, m)
    return found


def available(probe_fn: Callable[[str], list[str] | None] = probe) -> list[dict]:
    """Which add-ins can run right now. Prefers the named backend for each add-in,
    then the env endpoint, then any discovered local backend — so it works with
    whatever fleet you actually run."""
    found = discover(probe_fn)
    out = []
    for key, spec in ADDINS.items():
        label = (next((b for b in spec["prefers"] if b in found), None)
                 or ("env" if "env" in found else None)
                 or (next(iter(found), None)))
        base = found[label][0] if label else None
        out.append({"addin": key, "capability": spec["capability"],
                    "backend": label, "base_url": base,
                    "models": found[label][1] if label else None,
                    "enabled": label is not None})
    return out


def chat(base_url: str, model: str, messages: list[dict], *, timeout: float = 120.0) -> str:
    """Minimal OpenAI chat call; returns the assistant text."""
    body = json.dumps({"model": model, "messages": messages}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return data["choices"][0]["message"]["content"]


def reasoning_assess(watchlist: list[dict], base_url: str, model: str, **kw: Any) -> str:
    """Ask a reasoning model to prioritize + explain the watchlist (analyst aid)."""
    prompt = (
        "You are a maritime-domain-awareness analyst. Given this grey/dark-fleet "
        "watchlist (vessels flagged by AIS-behavior and sanctions heuristics), write a "
        "brief, defensive risk assessment: which vessels warrant review first and why, "
        "and what additional open-source checks (registry, imagery, ownership) would "
        "confirm or clear each. Describe and prioritize only — no operational/interdiction "
        "advice.\n\nWATCHLIST:\n" + json.dumps(watchlist, indent=2))
    return chat(base_url, model, [{"role": "user", "content": prompt}], **kw)


def build_vision_messages(image_ref: str, note: str = "") -> list[dict]:
    """OpenAI vision message: triage imagery for vessel presence/characteristics."""
    text = ("Describe any vessels visible in this maritime image for situational "
            "awareness: count, approximate size/type, and whether positions look "
            "consistent with normal traffic. Descriptive only." + (f" Context: {note}" if note else ""))
    return [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_ref}}]}]


def vision_assess(image_ref: str, base_url: str, model: str, note: str = "", **kw: Any) -> str:
    return chat(base_url, model, build_vision_messages(image_ref, note), **kw)
