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
    "06_fleet_network",
    "07_flag_hopping",
    "08_sts_correlation",
    "09_pattern_of_life",
    "10_cot_cop_export",
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
