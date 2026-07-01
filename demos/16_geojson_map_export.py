"""Scenario 16 - drop findings on a map (GeoJSON export).

`intel.to_geojson` renders any analyze() result as a valid GeoJSON FeatureCollection:
point findings become Points, two-position findings (a gap's from/to) become
LineStrings, and every feature carries the finding's scalar properties plus a label.
Open the output in Leaflet / Mapbox / QGIS / kepler.gl with zero dependencies.
Pure offline analysis of the bundled fixture.
"""
import json

from _common import messages, rule, bullet
from maritimeint.core import analyze
from maritimeint import intel


def main() -> None:
    msgs = messages()
    rule("MAP EXPORT  -  analyze() -> GeoJSON FeatureCollection (Leaflet/QGIS-ready)")

    report = analyze(msgs)
    gj = json.loads(intel.to_geojson(report))
    assert gj["type"] == "FeatureCollection"

    kinds = {}
    for f in gj["features"]:
        g = f["geometry"]
        k = g["type"] if g else "no-geometry"
        kinds[k] = kinds.get(k, 0) + 1

    print(f"\n{len(gj['features'])} feature(s):")
    for k, n in sorted(kinds.items()):
        bullet(f"{k:<13} {n}")

    mapped = [f for f in gj["features"] if f["geometry"]]
    if mapped:
        s = mapped[0]
        print("\nSample feature:")
        bullet(f"label   : {s['properties'].get('label')}", indent=7)
        bullet(f"geometry: {s['geometry']['type']} @ {s['geometry']['coordinates']}",
               indent=7)
    print(f"\n{len(mapped)} of {len(gj['features'])} features carry geometry and will "
          "render on a map.")


if __name__ == "__main__":
    main()
