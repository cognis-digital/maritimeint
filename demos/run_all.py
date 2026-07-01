"""Run every maritimeint demo scenario end to end.

    python demos/run_all.py

Each scenario loads the same bundled, offline AIS fixture and runs the real public
API, so they can be run in any order or on their own. The script exits 0 on
success, so it doubles as a smoke test.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SCENARIOS = [
    "01_osint_analyst_sweep",
    "02_sanctions_compliance",
    "03_port_security",
    "04_researcher_export",
    "05_gps_spoofing_ew",
    "06_dark_rendezvous_hunt",
    "07_cpa_tcpa_force_protection",
    "08_shadowing_surveillance",
    "09_convoy_greyfleet",
    "10_drift_distress",
    "11_zone_geofencing",
    "12_port_itineraries",
    "13_gps_spoofing_circles",
    "14_export_stix_tip",
    "15_watchlist_gate",
    "16_geojson_map_export",
    "17_encounters_suite",
    "18_zone_enriched_analysis",
    "19_loitering_sts_staging",
    "20_full_pipeline",
]


def main() -> None:
    for name in SCENARIOS:
        mod = importlib.import_module(name)
        mod.main()
    print("\n" + "=" * 72)
    print("  All demo scenarios completed.")
    print("=" * 72)


if __name__ == "__main__":
    main()
