"""Scenario 10 - Cursor-on-Target & KML-timeline export to a COP.

Detections are only useful if they reach the tools analysts already run. `to_cot`
renders geolocated findings as Cursor-on-Target `<event>` elements - the XML the
TAK / ATAK common-operating-picture ecosystem speaks - so a maritimeint run drops
straight onto a shared COP as track markers. `to_kml_timeline` renders the same
findings as time-stamped KML placemarks that play back on Google Earth's time slider.

Situational-awareness display only: a CoT event carries a position and a label, never
a task or an engagement order, and affiliation is always "unknown" (a-u-S), never
hostile. Pure offline analysis on the bundled Gulf fixture.
"""
import xml.etree.ElementTree as ET

from _common import messages, rule, bullet
from maritimeint.core import analyze
from maritimeint import intel


def main() -> None:
    msgs = messages()
    rule("COP EXPORT  -  Cursor-on-Target (TAK/ATAK) + KML timeline")

    report = analyze(msgs)
    cot = intel.to_cot(report)
    root = ET.fromstring(cot)
    events = root.findall("event")
    print(f"\nCoT: {len(events)} geolocated finding(s) rendered as <event> track markers\n")
    for ev in events[:6]:
        pt = ev.find("point")
        call = ev.find("detail/contact")
        bullet(f"{ev.attrib['type']}  {call.attrib.get('callsign', '') if call is not None else '':<28} "
               f"@ ({pt.attrib['lat']}, {pt.attrib['lon']})")
    if len(events) > 6:
        bullet(f"... and {len(events) - 6} more", indent=7)

    # every CoT affiliation stays "unknown" - never hostile
    affils = {ev.attrib["type"] for ev in events}
    print(f"\naffiliations emitted: {sorted(affils) or ['(none)']}  "
          "(a-u-S = unknown surface; never a-h- hostile)")

    kmlt = intel.to_kml_timeline(report)
    ET.fromstring(kmlt)  # must parse
    spans = kmlt.count("<TimeSpan>")
    stamps = kmlt.count("<TimeStamp>")
    print(f"\nKML timeline: well-formed, {spans} TimeSpan + {stamps} TimeStamp placemark(s)")
    print("  -> open in Google Earth and scrub the time slider to replay the picture.")

    print("\nSame detections, the formats the COP already ingests - no new tooling,\n"
          "no targeting semantics, just shared situational awareness.")


if __name__ == "__main__":
    main()
