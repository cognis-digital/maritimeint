"""MARITIMEINT - AIS vessel tracking & sanctions-evasion anomaly detection.

A zero-dependency OSINT toolkit for analyzing AIS (Automatic Identification
System) message streams to surface behaviors associated with sanctions
evasion and illicit maritime activity:

  * AIS gaps / "going dark" (transponder shutoff windows)
  * Implausible position jumps (impossible speed between fixes)
  * Loitering at sea (potential ship-to-ship transfer rendezvous)
  * Spoofing indicators (identity mismatch, static-pinned positions)
  * Vessel rendezvous detection (two ships meeting in open water)

Standard library only. No network access.
"""

from .core import (
    AISMessage,
    parse_messages,
    haversine_nm,
    detect_gaps,
    detect_speed_jumps,
    detect_loitering,
    detect_spoofing,
    detect_rendezvous,
    analyze,
)

TOOL_NAME = "maritimeint"
TOOL_VERSION = "1.0.0"

__all__ = [
    "AISMessage",
    "parse_messages",
    "haversine_nm",
    "detect_gaps",
    "detect_speed_jumps",
    "detect_loitering",
    "detect_spoofing",
    "detect_rendezvous",
    "analyze",
    "TOOL_NAME",
    "TOOL_VERSION",
]
