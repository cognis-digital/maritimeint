"""Scenario 4 - researchers & data teams.

A finding is only useful if it leaves the tool. maritimeint's `intel` module turns
any analyze() result into the four formats researchers actually use - GeoJSON (drop
on a Leaflet/QGIS/kepler.gl map), KML (Google Earth), STIX 2.1 (threat-intel
platforms), and CSV (notebooks/spreadsheets) - with zero dependencies. This
scenario runs the suite once and exports it four ways, showing each is well-formed.
Writes nothing to disk; everything is in-memory and offline.
"""
import csv
import io
import json
import xml.dom.minidom as minidom

from _common import messages, rule, bullet
from maritimeint.core import analyze
from maritimeint import intel


def main() -> None:
    msgs = messages()
    rule("RESEARCH EXPORT  -  one analysis, four standard formats, no deps")

    report = analyze(msgs)
    print(f"\nanalyze() produced {len(report['findings'])} findings. Exporting:\n")

    # GeoJSON -- valid FeatureCollection, parses, maps onto any GIS
    gj = json.loads(intel.to_geojson(report))
    geo_feats = sum(1 for f in gj["features"] if f["geometry"])
    bullet(f"GeoJSON : {gj['type']} with {len(gj['features'])} features "
           f"({geo_feats} with geometry, map-ready)")

    # KML -- well-formed XML (Google Earth / marine charting)
    kml = intel.to_kml(report)
    placemarks = minidom.parseString(kml).getElementsByTagName("Placemark")
    bullet(f"KML     : valid XML, {len(placemarks)} placemarks")

    # STIX 2.1 -- a bundle of indicator objects for TIP ingestion
    bundle = json.loads(intel.to_stix(report))
    inds = [o for o in bundle["objects"] if o["type"] == "indicator"]
    bullet(f"STIX 2.1: bundle id {bundle['id'][:24]}... with {len(inds)} indicators")

    # CSV -- flat table for pandas / spreadsheets
    rows = list(csv.DictReader(io.StringIO(intel.to_csv(report))))
    bullet(f"CSV     : {len(rows)} rows, columns = {list(rows[0].keys())}")

    print("\nReproducibility check: STIX ids are deterministic (uuid5 over the "
          "finding),\nso re-running yields byte-identical output - safe to diff in "
          "a pipeline.")
    again = json.loads(intel.to_stix(report))
    same = [o["id"] for o in again["objects"]] == [o["id"] for o in bundle["objects"]]
    bullet(f"second run produced identical indicator ids: {same}")


if __name__ == "__main__":
    main()
