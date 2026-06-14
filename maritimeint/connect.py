"""Bridge maritimeint's watchlist into the suite-wide `cognis-connect` integration SDK.

Maps each watchlist vessel to a canonical `Finding`, then forwards it to any platform
(STIX/MISP/Sigma/Splunk/Elastic/Slack/Discord/webhook). cognis-connect is a soft
dependency: if it isn't installed, `--emit` reports how to get it and the core is
unaffected.
"""

from __future__ import annotations

_SEV = {"high": "high", "medium": "medium", "low": "low"}


def watchlist_to_findings(result: dict):
    """Convert a locate() result into cognis_connect.Finding objects."""
    from cognis_connect.findings import Finding
    out = []
    for v in result.get("watchlist", []):
        tier = str(v.get("tier", "low")).lower()
        sanctioned = bool(v.get("sanctioned"))
        sev = "critical" if sanctioned else _SEV.get(tier, "low")
        reasons = v.get("reasons", [])
        out.append(Finding(
            title=f"{v.get('name') or v.get('mmsi')}: {reasons[0] if reasons else 'elevated risk'}",
            source="maritimeint",
            severity=sev,
            type="sanctions-hit" if sanctioned else "vessel-risk",
            description="; ".join(reasons),
            indicators={k: v.get(k) for k in ("mmsi", "imo") if v.get(k)},
            tags=["sanctioned"] if sanctioned else [],
            raw=v,
        ))
    return out


def forward(result: dict, target: str, *, url=None, token=None, dry_run=False):
    """Send the watchlist to `target` via cognis-connect. Returns a status dict/string."""
    try:
        from cognis_connect import misp, notify, sigma, siem, stix
    except ImportError:
        raise ImportError("--emit needs cognis-connect: "
                          "pip install git+https://github.com/cognis-digital/cognis-connect.git")
    findings = watchlist_to_findings(result)
    if target == "stix":
        return stix.to_bundle(findings)
    if target == "sigma":
        return sigma.to_rules(findings)
    if target == "misp":
        return misp.push(findings, url, token or "", dry_run=dry_run) if url else misp.to_event(findings)
    if target == "splunk":
        return siem.send_splunk(findings, url, token or "", dry_run=dry_run)
    if target == "elastic":
        return siem.send_elastic(findings, url, token=token, dry_run=dry_run)
    if target == "slack":
        return notify.send_slack(findings, url, header="maritimeint watchlist", dry_run=dry_run)
    if target == "discord":
        return notify.send_discord(findings, url, header="maritimeint watchlist", dry_run=dry_run)
    if target == "webhook":
        return siem.send_webhook(findings, url, token=token, dry_run=dry_run)
    raise ValueError(f"unknown emit target {target!r}")
