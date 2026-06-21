"""maritimeint — part of the Cognis Neural Suite."""
try:  # re-export the tool's public API + identity from core
    from maritimeint.core import *  # noqa: F401,F403
except Exception:  # pragma: no cover
    pass
try:
    from maritimeint.core import TOOL_NAME, TOOL_VERSION
except Exception:  # pragma: no cover
    TOOL_NAME = "maritimeint"
    TOOL_VERSION = "0.9.0"
__version__ = TOOL_VERSION

# Native, dependency-free intelligence export (GeoJSON / KML / STIX 2.1 / CSV).
try:
    from maritimeint.intel import (  # noqa: F401
        export, to_geojson, to_kml, to_stix, to_csv,
    )
except Exception:  # pragma: no cover
    pass
