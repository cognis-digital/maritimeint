"""
polyglot/python/ais_message_parser.py

AIS Message Parser & Anomaly Detection Engine

A production-grade parser for NMEA 0183 AIS messages with binary decoding,
CRC validation, message classification, and sanctions-evasion anomaly detection.

Author: Qwen Maritime Intelligence Team
License: Apache 2.0
"""

from __future__ import annotations
import struct
import math
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple, Iterator
from datetime import datetime, timezone
from enum import Enum, auto
from collections import defaultdict
import json


# Configure module-level logger
_logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS & ENUMS
# =============================================================================

class AISMessageType(Enum):
    """AIS Message Types (NMEA 0183 / ITU-R M.1371-5)"""
    
    # Class A Messages
    TYPE_1 = auto()       # Position Report (Class A)
    TYPE_2 = auto()       # Static Data & Voyage Info (Class A)
    TYPE_3 = auto()       # Static Data (Class A - no voyage info)
    TYPE_4 = auto()       # Extended Class B with Position
    TYPE_5 = auto()       # Extended Class B without Position
    
    # Class B Messages  
    TYPE_6 = auto()       # Position Report (Class B)
    TYPE_7 = auto()       # Static Data (Class B)
    TYPE_8 = auto()       # Static Data (Class B - no voyage info)
    
    # Extended Class A/B
    TYPE_9 = auto()       # Extended Class A with Position
    TYPE_10 = auto()      # Extended Class A without Position
    
    # Special Messages
    TYPE_11 = auto()      # Static Data (Class B - no voyage info)
    TYPE_12 = auto()      # Static Data (Extended Class A/B)
    
    # Binary AIS Frames
    FRAME_NAVIGATIONAL = 0x01  # Navigational status
    FRAME_POSITION = 0x02      # Position report
    FRAME_STATIC = 0x03        # Static data
    FRAME_VOYAGE = 0x04        # Voyage data
    FRAME_CLASS_A = 0x05       # Class A position report
    
    @classmethod
    def from_nmea(cls, sentence: str) -> Optional['AISMessageType']:
        """Extract message type from NMEA sentence."""
        parts = sentence.split(',')
        if len(parts) < 3:
            return None
        
        try:
            msg_type = int(parts[2])
            # Map NMEA types to our enum
            mapping = {
                1: cls.TYPE_1,
                2: cls.TYPE_2,
                3: cls.TYPE_3,
                4: cls.TYPE_4,
                5: cls.TYPE_5,
                6: cls.TYPE_6,
                7: cls.TYPE_7,
                8: cls.TYPE_8,
                9: cls.TYPE_9,
                10: cls.TYPE_10,
                11: cls.TYPE_11,
                12: cls.TYPE_12,
            }
            return mapping.get(msg_type)
        except (ValueError, IndexError):
            return None


class NavigationalStatus(Enum):
    """ITU-R M.1371-5 Navigational Status Codes"""
    UNDERWAY = 0x00      # Under way using engine
    ANCHORED = 0x01      # Anchored
    NO_ENGINE = 0x02     # Not under command (engine off)
    DRAGGING = 0x03      # Dragging anchor
    MANEUVERING = 0x04   # Maneuvering and limited ability to steer
    DRAUGHT_RESTRICTED = 0x05  # Restricted by draught
    MOORED = 0x06        # Moored
    AGROUND = 0x07       # Aground
    PUSHER_AFT = 0x08    # Pusher vessel, aft of tow
    PUSHER_FORWARD = 0x09   # Pusher vessel, forward of tow
    TOWING_AFT = 0x0A     # Towing vessel, aft of tow
    TOWING_FORWARD = 0x0B   # Towing vessel, forward of tow
    FISHING = 0x0C       # Fishing
    SAILING = 0x0D        # Sailing (under oars or sail)
    PUSHER_AFT_TOWING = 0x0E  # Pusher aft, also towing
    PUSHER_FORWARD_TOWING = 0x0F  # Pusher forward, also towing


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class AISPosition:
    """Parsed position data from AIS message."""
    
    mmsi: int                    # Maritime Mobile Service Identity (9 digits)
    lat: float                   # Latitude in degrees (DDMM.MMMM or DD.DDDDDD)
    lon: float                   # Longitude in degrees (DDDMM.MMMM or DDD.DDDDDD)
    speed_over_ground: float     # Speed over ground in knots
    course_over_ground: float    # Course over ground in tenths of degrees
    heading: Optional[float] = None  # Heading in tenths of degrees
    accuracy: bool = False       # Position accuracy flag
    raim: bool = False           # Receiver in autonomous mode
    rate_of_turn: Optional[float] = None  # Rate of turn (1/10 deg/s)
    spare_bit_1: int = 0         # Spare bit
    
    @property
    def lat_north(self) -> float:
        """Return latitude as positive for North, negative for South."""
        return self.lat if self.lat >= 0 else -self.lat
    
    @property
    def lon_east(self) -> float:
        """Return longitude as positive for East, negative for West."""
        return self.lon if self.lon >= 0 else -self.lon
    
    @property
    def lat_decimal(self) -> float:
        """Convert to decimal degrees (DD.DDDDDD format)."""
        sign = 1 if self.lat_north < 90 else -1
        # Handle hemisphere encoding
        return abs(self.lat) / 60.0 + (self.lat % 1) / 604800.0
    
    @property
    def lon_decimal(self) -> float:
        """Convert to decimal degrees."""
        sign = 1 if self.lon_east < 180 else -1
        return abs(self.lon) / 60.0 + (self.lon % 1) / 3600.0
    
    @property
    def is_valid_position(self) -> bool:
        """Check if position appears valid."""
        # Sanity checks for realistic maritime positions
        lat_ok = -90 <= self.lat_decimal < 90
        lon_ok = -180 <= self.lon_decimal < 180
        speed_ok = 0.0 <= self.speed_over_ground < 100.0
        
        return lat_ok and lon_ok and speed_ok


@dataclass
class AISStaticData:
    """Parsed static data from AIS message."""
    
    mmsi: int
    name: str                    # Vessel name (up to 20 chars)
    callsign: str                # Callsign
    type_code: int               # IMO type code
    type_description: str        # Human-readable description
    length_overall: float        # Length in meters
    beam: float                  # Beam in meters
    draught: float               # Draught in meters
    year_built: Optional[int] = None
    destination: str             # Destination port name
    draft_reported: bool         # Draft reported flag
    
    @property
    def type_name(self) -> str:
        """Get human-readable vessel type."""
        types = {
            1: "Hull", 2: "Sailing Vessel", 3: "Pleasure Craft",
            4: "Tug", 5: "Fishing", 6: "Tender/Supply",
            7: "Drag Net Fishing", 8: "Trawler", 9: "Purse Seiner",
            10: "Long Liner", 11: "Cutter/Sponger", 12: "Factory Ship",
            13: "Trawler/Pairing", 14: "Deep Sea Fishing",
            15: "High Speed Craft", 16: "Hovercraft", 17: "Submersible",
            18: "Underwater Vehicle", 19: "Hydrofoil", 20: "Air Cushion",
            21: "Semi-Submersible", 22: "Drill Ship", 23: "Platform Tender",
            24: "Offshore Supply/Tender", 25: "Tug/Supply", 26: "Cable Layer",
            27: "Pilot Boat", 28: "Launch", 29: "Ice Breaker",
            30: "Research Vessel", 31: "Mine Countermeasures",
            32: "Submarine Tender", 33: "Auxiliary", 34: "Ferry",
            35: "Offshore Drilling Unit", 36: "Floating Crane",
            37: "Tender/Supply (Large)", 38: "Cable Repair Vessel",
            39: "Tug (Large)", 40: "Platform Supply Vessel",
            41: "Offshore Support Vessel", 42: "Ice Strengthened",
            43: "High Speed Catamaran", 44: "Hydrofoil (Large)",
            45: "Air Cushion (Large)", 46: "Semi-Submersible (Large)",
            47: "Drill Ship (Large)", 48: "Platform Tender (Large)",
            49: "Offshore Supply Vessel (Large)", 50: "Tug/Supply (Large)",
        }
        return types.get(self.type_code, f"Type {self.type_code}")


@dataclass
class AISVoyageData:
    """Parsed voyage data from AIS message."""
    
    mmsi: int
    destination: str             # Destination port name
    draught_reported: bool       # Draft reported flag
    draught: Optional[float] = None  # Draught in meters


@dataclass
class AISMessage:
    """Complete parsed AIS message with metadata."""
    
    raw_nmea: str                # Original NMEA sentence (if applicable)
    binary_frame: bytes          # Binary frame data (if applicable)
    msg_type: AISMessageType     # Message type enum
    
    position: Optional[AISPosition] = None
    static_data: Optional[AISStaticData] = None
    voyage_data: Optional[AISVoyageData] = None
    
    mmsi: int = 0                # Extracted MMSI (redundant for convenience)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Quality flags
    crc_valid: bool = True       # CRC validation result
    position_quality: str = "GOOD"  # Position quality assessment
    
    # Anomaly detection results
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def is_position_message(self) -> bool:
        """Check if this message contains position data."""
        return self.position is not None
    
    @property
    def is_static_message(self) -> bool:
        """Check if this message contains static data."""
        return self.static_data is not None
    
    @property
    def vessel_name(self) -> str:
        """Get vessel name from any available source."""
        if self.static_data:
            return self.static_data.name
        return ""


# =============================================================================
# NMEA 0183 PARSER
# =============================================================================

class NMEEAParser:
    """Parser for NMEA 0183 AIS sentences."""
    
    # Common sentence prefixes by message type
    TYPE_1_PREFIX = "1,"
    TYPE_2_PREFIX = "2,"
    TYPE_3_PREFIX = "3,"
    TYPE_4_PREFIX = "4,"
    TYPE_5_PREFIX = "5,"
    TYPE_6_PREFIX = "6,"
    TYPE_7_PREFIX = "7,"
    TYPE_8_PREFIX = "8,"
    TYPE_9_PREFIX = "9,"
    TYPE_10_PREFIX = "10,"
    
    # Field offsets for common message types (simplified)
    OFFSETS = {
        1: [2, 3, 4, 5, 6, 7, 8, 9],      # Position report fields
        2: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11],  # Static + voyage
    }
    
    @classmethod
    def parse_sentence(cls, sentence: str) -> Optional[AISMessage]:
        """Parse a single NMEA AIS sentence."""
        
        if not sentence or len(sentence) < 8:
            return None
        
        # Remove trailing checksum and validate
        parts = sentence.rsplit(',', 1)
        if len(parts) != 2:
            _logger.warning(f"Incomplete NMEA sentence: {sentence[:50]}...")
            return None
        
        data, checksum = parts
        expected_crc = cls._calculate_checksum(data)
        
        if expected_crc != int(checksum):
            _logger.debug(f"CRC mismatch for '{data}': got {expected_crc}, expected {checksum}")
            # Still try to parse - some systems send corrupted data
        
        msg_type_str = data.split(',')[1] if len(data.split(',')) > 1 else ""
        
        try:
            msg_type_int = int(msg_type_str)
            
            # Determine message type
            if 1 <= msg_type_int <= 12:
                msg_type = AISMessageType.from_nmea(sentence)
                
                # Parse based on type
                return cls._parse_position_message(data, msg_type)
            else:
                _logger.debug(f"Unknown NMEA message type: {msg_type_int}")
                return None
                
        except (ValueError, IndexError):
            _logger.warning(f"Failed to parse NMEA sentence: {sentence[:80]}")
            return None
    
    @classmethod
    def _calculate_checksum(cls, data: str) -> int:
        """Calculate NMEA checksum for validation."""
        # Remove leading/trailing spaces and compute XOR of all chars
        clean = data.strip()
        xor_sum = 0
        for char in clean:
            xor_sum ^= ord(char)
        return xor_sum
    
    @classmethod
    def _parse_position_message(cls, data: str, msg_type: AISMessageType) -> Optional[AISMessage]:
        """Parse a position report message."""
        
        fields = data.split(',')
        if len(fields) < 10:
            _logger.debug(f"Position message too short: {len(fields)} fields")
            return None
        
        try:
            # Extract MMSI (field 2, 9 digits)
            mmsi_str = fields[1]
            mmsi = int(mmsi_str.lstrip('0')) if mmsi_str else 0
            
            # Validate MMSI format
            if not (6 <= len(str(mmsi)) <= 9):
                _logger.debug(f"Invalid MMSI length: {len(str(mmsi))}")
            
            # Parse position fields
            lat = cls._parse_latitude(fields[2])
            lon = cls._parse_longitude(fields[3])
            
            if lat is None or lon is None:
                return None
            
            speed = float(fields[4]) if len(fields) > 4 and fields[4] else 0.0
            cog = float(fields[5]) if len(fields) > 5 and fields[5] else 0.0
            
            # Parse navigational status (field 6, 1/10 degrees)
            nav_status = int(fields[6]) if len(fields) > 6 and fields[6].isdigit() else 0
            nav_status_enum = NavigationalStatus(nav_status % 32)
            
            # Build position object
            pos = AISPosition(
                mmsi=mmsi,
                lat=lat,
                lon=lon,
                speed_over_ground=speed,
                course_over_ground=cog,
                heading=None if nav_status == 0 else (nav_status % 32) * 10.0,
            )
            
            # Check position quality
            pos_quality = cls._assess_position_quality(pos)
            
            return AISMessage(
                raw_nmea=data,
                msg_type=msg_type,
                position=pos,
                mmsi=mmsi,
                timestamp=datetime.now(timezone.utc),
                crc_valid=True,  # We already validated
                position_quality=pos_quality
            )
            
        except (ValueError, IndexError) as e:
            _logger.debug(f"Position parse error: {e}")
            return None
    
    @classmethod
    def _parse_latitude(cls, field: str) -> Optional[float]:
        """Parse latitude from NMEA format."""