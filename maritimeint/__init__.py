"""maritimeint — part of the Cognis Neural Suite."""
try:  # re-export the tool's public API + identity from core
    from maritimeint.core import *  # noqa: F401,F403
except Exception:  # pragma: no cover
    pass
try:
    from maritimeint.core import TOOL_NAME, TOOL_VERSION
except Exception:  # pragma: no cover
    TOOL_NAME = "maritimeint"
    TOOL_VERSION = "1.0.0"
__version__ = TOOL_VERSION

# Native, dependency-free intelligence export (GeoJSON / KML / STIX 2.1 / CSV / CoT).
try:
    from maritimeint.intel import (  # noqa: F401
        export, to_geojson, to_kml, to_stix, to_csv, to_cot, to_kml_timeline,
    )
except Exception:  # pragma: no cover
    pass

# Track-interaction & behaviour detectors (CPA/TCPA, shadowing, convoy, drift).
try:
    from maritimeint.encounters import (  # noqa: F401
        detect_close_quarters, detect_shadowing, detect_convoy, detect_drift,
        analyze_encounters,
    )
except Exception:  # pragma: no cover
    pass

# Fleet / network analytics (contact graph, rings, flag-hopping, identity rings).
try:
    from maritimeint.fleet import (  # noqa: F401
        contact_network, fleet_rings, flag_hopping, identity_rings,
        analyze_fleet, flag_of, mid_of,
    )
except Exception:  # pragma: no cover
    pass

# Pattern-of-life & multi-signal correlation (gap timeline, STS scoring, POL).
try:
    from maritimeint.patterns import (  # noqa: F401
        gap_timeline, sts_transfer_score, pattern_of_life, analyze_patterns,
    )
except Exception:  # pragma: no cover
    pass
