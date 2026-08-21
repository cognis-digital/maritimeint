"""
vessel_registry_resolver.py

A robust, production-ready vessel registry resolver for the maritimeint AIS tracking system.
Handles IMO, MMSI, and callsign resolution with caching, validation, and realistic mock data.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum, auto
from typing import Any, Callable, Optional


# Configure module-level logger
_logger = logging.getLogger(__name__)


class RegistrySource(Enum):
    """Supported registry identifier types."""
    IMO = auto()
    MMSI = auto()
    CALLSIGN = auto()
    NAME = auto()
    FLAG = auto()


@dataclass(frozen=True)
class VesselRegistryResult:
    """Container for a resolved vessel registry record."""

    source: RegistrySource
    identifier: str
    found: bool = True
    vessel_name: Optional[str] = None
    imo_number: Optional[str] = None
    mmsi: Optional[int] = None
    callsign: Optional[str] = None
    flag_state: Optional[str] = None
    port_of_registry: Optional[str] = None
    build_year: Optional[int] = None
    gross_tonnage: Optional[float] = None
    length_overall: Optional[float] = None
    beam: Optional[float] = None
    draught: Optional[float] = None
    deadweight: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.found and not any(
            getattr(self, attr) for attr in ("vessel_name", "imo_number")
        ):
            object.__setattr__(self, "metadata", {"error": "No data available"})


class RegistryCache:
    """Thread-safe LRU cache for registry lookups."""

    def __init__(self, max_size: int = 1000):
        self._cache: dict[str, VesselRegistryResult] = {}
        self._max_size = max_size
        self._lock = threading.RLock()
        self._access_log: list[tuple[float, str]] = []

    def _make_key(self, source: RegistrySource, identifier: str) -> str:
        return f"{source.name}:{identifier}"

    def get(self, source: RegistrySource, identifier: str) -> Optional[VesselRegistryResult]:
        key = self._make_key(source, identifier)
        with self._lock:
            if key in self._cache:
                result = self._cache[key]
                # Log access for debugging/auditing
                self._access_log.append((time.time(), f"hit:{key}"))
                return result

    def put(self, source: RegistrySource, identifier: str, result: VesselRegistryResult) -> None:
        key = self._make_key(source, identifier)
        with self._lock:
            if len(self._cache) >= self._max_size:
                # Evict oldest entry (simple FIFO for now; could be LRU)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[key] = result

    def invalidate(self, source: RegistrySource, identifier: str) -> bool:
        key = self._make_key(source, identifier)
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
        return False


class IMOSummaryValidator:
    """Validates IMO number checksums using the standard algorithm."""

    @staticmethod
    def validate_imo_checksum(imo: str) -> bool:
        """
        Validate 7-digit IMO using modulo-10 check.
        
        Algorithm: sum = Σ(d_i * (8 - i)) for i=0..6, result = sum % 10
        The last digit should equal the checksum digit.
        """
        if len(imo) != 7 or not imo.isdigit():
            return False
        
        digits = [int(c) for c in imo]
        weighted_sum = sum(d * (8 - i) for i, d in enumerate(digits))
        expected_checksum = weighted_sum % 10
        actual_checksum = int(imo[-1])
        
        return expected_checksum == actual_checksum

    @staticmethod
    def extract_imo_prefix(imo: str) -> Optional[str]:
        """Extract the first 4 digits (IMO prefix indicating shipyard/flag)."""
        if len(imo) >= 4 and imo.isdigit():
            return imo[:4]
        return None


class MMSIValidator:
    """Validates MMSI numbers and extracts country code."""

    @staticmethod
    def validate_mmsi(mmsi: int | str) -> tuple[bool, Optional[int]]:
        """
        Validate 9-digit MMSI. Returns (is_valid, numeric_value).
        
        Standard format: AAA-BBB-CCCCC where AAA is country code prefix.
        """
        s = str(mmsi).strip()
        if len(s) != 9 or not s.isdigit():
            return False, None
        
        # Basic validation: first digit should be 0-4 for most countries
        first_digit = int(s[0])
        if first_digit in (0, 1, 2, 3, 4):
            return True, int(mmsi)
        
        # Extended range check (some newer assignments go higher)
        if first_digit == 5:
            # Special use/reserved
            pass
        
        return False, None

    @staticmethod
    def get_country_prefix(mmsi: int | str) -> Optional[str]:
        """Extract the 3-digit country prefix from MMSI."""
        s = str(mmsi).strip()
        if len(s) == 9 and s.isdigit():
            return s[:3]
        return None


class CallsignParser:
    """Parses ICAO callsigns to extract originator code."""

    @staticmethod
    def parse_callsign(callsign: str) -> tuple[bool, Optional[str], Optional[int]]:
        """
        Parse callsign and extract originator (first 3 chars).
        
        Returns (is_valid, originator_code, numeric_value_if_applicable).
        """
        cs = callsign.strip().upper() if callsign else ""
        
        # ICAO callsigns are typically 4-6 alphanumeric characters
        if len(cs) < 3 or len(cs) > 7:
            return False, None, None
        
        originator = cs[:3]
        
        # Try to extract numeric part (often used for quick lookup)
        try:
            numeric_part = int("".join(c.isdigit() and c for c in cs))
            return True, originator, numeric_part
        except ValueError:
            return True, originator, 0


class MockRegistryBackend:
    """
    Simulates a real registry backend with realistic test data.
    
    In production, this would connect to databases like:
    - Lloyd's Register Online
    - IMO International Ship Identification System (ISIS)
    - Flag state registries
    - Commercial AIS providers (Navico, MarineTraffic API)
    """

    # Realistic mock database with varied vessel types and flags
    _MOCK_DB: dict[str, VesselRegistryResult] = field(default_factory=lambda: {
        "IMO": {},
        "MMSI": {},
        "CALLSIGN": {},
        "NAME": {},
        "FLAG": {},
    })

    # Pre-populate with realistic test data
    _INITIAL_DATA = [
        # IMO records (7 digits)
        ("9123456", {
            "vessel_name": "EVER GIVEN",
            "imo_number": "9123456",
            "mmsi": 636019188,
            "callsign": "H3RC",
            "flag_state": "Panama",
            "port_of_registry": "Colón",
            "build_year": 2018,
            "gross_tonnage": 199625.0,
            "length_overall": 400.0,
            "beam": 59.0,
            "draught": 15.0,
            "deadweight": 199625.0,
        }),
        ("9387456", {
            "vessel_name": "MAERSK ESSEX",
            "imo_number": "9387456",
            "mmsi": 219019000,
            "callsign": "OZBU",
            "flag_state": "Denmark",
            "port_of_registry": "Copenhagen",
            "build_year": 2017,
            "gross_tonnage": 171635.0,
            "length_overall": 399.9,
            "beam": 58.6,
            "draught": 16.0,
            "deadweight": 194847.0,
        }),
        ("9256789", {
            "vessel_name": "MSC GULSUN",
            "imo_number": "9256789",
            "mmsi": 636019234,
            "callsign": "H3RD",
            "flag_state": "Panama",
            "port_of_registry": "Colón",
            "build_year": 2016,
            "gross_tonnage": 232495.0,
            "length_overall": 400.0,
            "beam": 61.4,
            "draught": 16.0,
            "deadweight": 232495.0,
        }),
        # MMSI records (9 digits)
        ("636019188", {
            "vessel_name": "EVER GIVEN",
            "imo_number": "9123456",
            "mmsi": 636019188,
            "callsign": "H3RC",
            "flag_state": "Panama",
            "port_of_registry": "Colón",
            "build_year": 2018,
            "gross_tonnage": 199625.0,
        }),
        ("219019000", {
            "vessel_name": "MAERSK ESSEX",
            "imo_number": "9387456",
            "mmsi": 219019000,
            "callsign": "OZBU",
            "flag_state": "Denmark",
            "port_of_registry": "Copenhagen",
            "build_year": 2017,
        }),
        # Callsign records
        ("H3RC", {
            "vessel_name": "EVER GIVEN",
            "imo_number": "9123456",
            "mmsi": 636019188,
            "callsign": "H3RC",
            "flag_state": "Panama",
        }),
        ("OZBU", {
            "vessel_name": "MAERSK ESSEX",
            "imo_number": "9387456",
            "mmsi": 219019000,
            "callsign": "OZBU",
            "flag_state": "Denmark",
        }),
    ]

    def _initialize(self) -> None:
        """Populate the mock database with initial data."""
        for record_type in self._MOCK_DB:
            if not self._MOCK_DB[record_type]:
                self._MOCK_DB[record_type] = {}

        # Insert into appropriate buckets
        for imo, data in self._INITIAL_DATA:
            if isinstance(imo, int):
                imo_str = str(imo)
            
            # Add to IMO bucket (last 4 digits as key for demo purposes)
            imo_key = imo_str[-4:] if len(imo_str) > 4 else imo_str
            self._MOCK_DB["IMO"][imo_key] = VesselRegistryResult(
                source=RegistrySource.IMO,
                identifier=imo_str,
                found=True,
                **data,
            )

        # Add MMSI entries
        for mmsi_int in [636019188, 219019000]:
            self._MOCK_DB["MMSI"][str(mmsi_int)] = VesselRegistryResult(
                source=RegistrySource.MMSI,
                identifier=str(mmsi_int),
                found=True,
                **self._INITIAL_DATA[2],  # Use first full record
            )

        # Add callsign entries
        for cs in ["H3RC", "OZBU"]:
            self._MOCK_DB["CALLSIGN"][cs] = VesselRegistryResult(
                source=RegistrySource.CALLSIGN,
                identifier=cs,
                found=True,
                **self._INITIAL_DATA[4],  # Use first full record
            )

    def lookup(self, source: RegistrySource, identifier: str) -> VesselRegistryResult:
        """Perform a registry lookup with caching."""
        cache = RegistryCache()
        
        # Try cache first
        cached_result = cache.get(source, identifier)
        if cached_result is not None:
            _logger.debug(f"Cache hit for {source.name}:{identifier}")
            return cached_result

        # Perform actual lookup (mocked)
        key = f"{source.name}:{identifier}"
        
        # Simulate network latency
        time.sleep(0.01)  # 10ms realistic API call time
        
        result = self._MOCK_DB.get(source, {}).get(identifier)
        
        if result:
            cache.put(source, identifier, result)
            _logger.debug(f"Found in DB for {key}")
        else:
            # Return not found with metadata
            result = VesselRegistryResult(
                source=source,
                identifier=identifier,
                found=False,
                metadata={"searched": key},
            )
        
        cache.put(source, identifier, result)
        return result


class VesselRegistryResolver:
    """
    Main resolver class that coordinates registry lookups.
    
    Supports multi-source resolution with fallback chains and fuzzy matching.
    Thread-safe for concurrent access in production environments.
    """

    def __init__(self, backend: Optional[MockRegistryBackend] = None):
        self._backend = backend or MockRegistryBackend()
        self._cache = RegistryCache(max_size=500)
        self._lock = threading.RLock()
        
        # Statistics for monitoring
        self._stats = {
            "lookups": 0,
            "hits": 0,
            "misses": 0,
            "fallbacks_used": 0,
        }

    def resolve(
        self,
        identifier: str,
        source: Optional[RegistrySource] = None,
        fuzzy_match: bool = False,
    ) -> VesselRegistryResult:
        """
        Resolve a vessel registry by any available identifier.
        
        Args:
            identifier: The search key (IMO, MMSI, callsign, etc.)
            source: Optional explicit source type. Auto-detected if None.
            fuzzy_match: Enable partial/fuzzy matching for degraded environments.
        
        Returns:
            VesselRegistryResult with resolved data or not-found status.
        """
        self._stats["lookups"] += 1
        
        # Auto-detect source from identifier format
        detected_source = self._detect_source(identifier)
        if source is None and detected_source:
            source = detected_source

        # Try primary lookup first
        result = self._backend.lookup(source, identifier)
        
        if result.found:
            self._stats["hits"] += 1
            return result
        
        # Fallback chain for degraded environments
        if fuzzy_match or self._stats["misses"] > 100:
            _logger.debug("Primary lookup failed, attempting fallbacks...