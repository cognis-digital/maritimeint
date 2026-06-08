"""MARITIMEINT command-line interface."""
from cognis_core import build_cli
from maritimeint.core import scan, TOOL_NAME, TOOL_VERSION

main = build_cli(
    tool_name=TOOL_NAME,
    tool_version=TOOL_VERSION,
    description="AIS vessel tracking & sanctions-evasion anomaly detection",
    scan_fn=scan,
)

if __name__ == "__main__":
    import sys
    sys.exit(main())
