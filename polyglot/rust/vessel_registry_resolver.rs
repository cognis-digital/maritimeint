use chrono::{DateTime, Duration, Utc};
use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fmt;
use thiserror::Error;

// ============================================================================
// ERRORS
// ============================================================================

#[derive(Error, Debug)]
pub enum ResolverError {
    #[error("Invalid MMSI format: {0}")]
    InvalidMmsi(String),
    
    #[error("AIS message parse error: {0}")]
    AisParse(String),
    
    #[error("Registry lookup failed for MMSI: {0}"),
    RegistryLookupFailed(u64),
    
    #[error("Timestamp parsing error: {0}"),
    TimestampError(String),
}

// ============================================================================
// CONSTANTS & CONFIGURATION
// ============================================================================

pub mod config {
    use std::time::Duration;
    
    pub const DEFAULT_CACHE_TTL: Duration = Duration::from_secs(3600); // 1 hour
    
    pub const HIGH_RISK_FLAGS: &[&str] = &[
        "LR", "PA", "TC", "YV", "VE", "SY", "AO"
    ];
    
    pub const SANCTIONED_REGIONS: &[(String, f64)] = &[
        // Red Sea / Suez chokepoint
        ("Red Sea", 25.0),
        // Strait of Hormuz
        ("Strait of Hormuz", 27.0),
        // Gulf of Guinea
        ("Gulf of Guinea", 10.0),
    ];
    
    pub const RAPID_FLAG_CHANGE_THRESHOLD_DAYS: u32 = 90;
}

// ============================================================================
// DATA MODELS
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mmsi {
    pub value: u64,
    pub prefix: u8,
    pub suffix: u8,
}

impl fmt::Display for Mmsi {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:09}", self.value)
    }
}

#[derive(Debug, Clone)]
pub struct Vessel {
    pub mmsi: Mmsi,
    pub name: String,
    pub callsign: Option<String>,
    pub flag: String,
    pub registry: RegistryInfo,
    pub built_year: u16,
    pub gross_tonnage: f64,
    pub length_meters: f64,
    pub beam_meters: f64,
}

impl Vessel {
    pub fn new(
        mmsi: Mmsi,
        name: String,
        flag: String,
        registry: RegistryInfo,
        built_year: u16,
        gross_tonnage: f64,
        length_meters: f64,
        beam_meters: f64,
    ) -> Self {
        Vessel {
            mmsi,
            name,
            callsign: None,
            flag,
            registry,
            built_year,
            gross_tonnage,
            length_meters,
            beam_meters,
        }
    }

    pub fn with_callsign(mut self, callsign: String) -> Self {
        self.callsign = Some(callsign);
        self
    }
}

#[derive(Debug, Clone)]
pub struct RegistryInfo {
    pub country_code: String,
    pub registry_name: String,
    pub is_high_risk: bool,
    pub risk_score: u8, // 0-100
}

impl Default for RegistryInfo {
    fn default() -> Self {
        RegistryInfo {
            country_code: "XX".to_string(),
            registry_name: "Unknown".to_string(),
            is_high_risk: false,
            risk_score: 0,
        }
    }
}

// ============================================================================
// AIS MESSAGE PARSING
// ============================================================================

#[derive(Debug, Clone)]
pub struct AisMessage {
    pub mmsi: Mmsi,
    pub timestamp: DateTime<Utc>,
    pub vessel_name: String,
    pub callsign: Option<String>,
    pub latitude: f64,
    pub longitude: f64,
    pub speed_knots: f64,
    pub course_degrees: f64,
    pub rudder_angle: i8,
    pub draught_meters: f64,
    pub destination: String,
    pub draft_reported: bool,
}

impl AisMessage {
    pub fn new(
        mmsi: Mmsi,
        timestamp: DateTime<Utc>,
        vessel_name: String,
        callsign: Option<String>,
        latitude: f64,
        longitude: f64,
        speed_knots: f64,
        course_degrees: f64,
        rudder_angle: i8,
        draught_meters: f64,
        destination: String,
        draft_reported: bool,
    ) -> Self {
        AisMessage {
            mmsi,
            timestamp,
            vessel_name,
            callsign,
            latitude,
            longitude,
            speed_knots,
            course_degrees,
            rudder_angle,
            draught_meters,
            destination,
            draft_reported,
        }
    }

    pub fn is_valid(&self) -> bool {
        self.mmsi.value > 0 && 
        (self.latitude.abs() <= 90.0 || self.longitude.abs() <= 180.0)
    }
}

// ============================================================================
// REGISTRY DATABASE
// ============================================================================

#[derive(Debug, Clone)]
pub struct RegistryDatabase {
    registries: HashMap<String, RegistryInfo>,
    vessels_by_mmsi: IndexMap<u64, Vessel>,
    high_risk_flags: HashSet<&'static str>,
}

impl Default for RegistryDatabase {
    fn default() -> Self {
        let mut db = RegistryDatabase::new();
        
        // Initialize with known registries
        db.add_registry("US", "United States (US)", false, 10);
        db.add_registry("UK", "United Kingdom (UK)", false, 15);
        db.add_registry("DE", "Germany (DE)", false, 20);
        db.add_registry("FR", "France (FR)", false, 20);
        db.add_registry("NL", "Netherlands (NL)", false, 20);
        db.add_registry("NO", "Norway (NO)", false, 25);
        db.add_registry("JP", "Japan (JP)", false, 30);
        db.add_registry("KR", "South Korea (KR)", false, 30);
        db.add_registry("CN", "China (CN)", true, 45);
        db.add_registry("BR", "Brazil (BR)", true, 40);
        
        // High risk flags
        for flag in config::HIGH_RISK_FLAGS {
            db.high_risk_flags.insert(*flag);
        }
        
        db
    }
}

impl RegistryDatabase {
    pub fn new() -> Self {
        let mut db = RegistryDatabase {
            registries: HashMap::new(),
            vessels_by_mmsi: IndexMap::new(),
            high_risk_flags: HashSet::new(),
        };
        
        db.add_registry("US", "United States (US)", false, 10);
        db.add_registry("UK", "United Kingdom (UK)", false, 15);
        db.add_registry("DE", "Germany (DE)", false, 20);
        db.add_registry("FR", "France (FR)", false, 20);
        db.add_registry("NL", "Netherlands (NL)", false, 20);
        db.add_registry("NO", "Norway (NO)", false, 25);
        db.add_registry("JP", "Japan (JP)", false, 30);
        db.add_registry("KR", "South Korea (KR)", false, 30);
        db.add_registry("CN", "China (CN)", true, 45);
        db.add_registry("BR", "Brazil (BR)", true, 40);
        
        for flag in config::HIGH_RISK_FLAGS {
            db.high_risk_flags.insert(*flag);
        }
        
        db
    }

    pub fn add_registry(&mut self, code: &str, name: &str, is_high_risk: bool, risk_score: u8) {
        let info = RegistryInfo {
            country_code: code.to_string(),
            registry_name: name.to_string(),
            is_high_risk,
            risk_score,
        };
        
        self.registries.insert(code.to_uppercase().to_string(), info);
    }

    pub fn get_registry(&self, flag: &str) -> Option<&RegistryInfo> {
        let key = flag.trim().to_uppercase();
        self.registries.get(&key).cloned()
    }

    pub fn is_high_risk_flag(&self, flag: &str) -> bool {
        if let Some(info) = self.get_registry(flag) {
            info.is_high_risk || config::HIGH_RISK_FLAGS.contains(&flag.as_str())
        } else {
            false
        }
    }

    pub fn get_or_create_vessel(
        &mut self,
        mmsi: Mmsi,
        vessel_name: String,
        flag: String,
        timestamp: DateTime<Utc>,
    ) -> Option<&Vessel> {
        // Check if we already have this vessel
        if let Some(existing) = self.vessels_by_mmsi.get(&mmsi.value) {
            return Some(existing);
        }

        // Create new vessel with default registry info
        let registry = self.get_registry(&flag).unwrap_or(&RegistryInfo::default());
        
        let vessel = Vessel::new(
            mmsi,
            vessel_name.clone(),
            flag,
            registry.clone(),
            2015, // Default year
            10_000.0, // Default tonnage
            180.0,    // Default length
            30.0,     // Default beam
        );

        self.vessels_by_mmsi.insert(mmsi.value, vessel);
        Some(self.vessels_by_mmsi.get(&mmsi.value).unwrap())
    }
}

// ============================================================================
// ANOMALY DETECTOR
// ============================================================================

#[derive(Debug)]
pub struct AnomalyReport {
    pub vessel: Option<Vessel>,
    pub anomaly_type: AnomalyType,
    pub severity: SeverityLevel,
    pub description: String,
    pub evidence: Vec<AnomalyEvidence>,
    pub timestamp: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub enum AnomalyType {
    RapidFlagChange,
    FlagHoppingPattern,
    HighRiskRegistryUsage,
    SimilarNameDifferentMmsi,
    MMSIReuse,
    BulkRegistration,
    UnknownVesselAge,
    GenericVesselName,
}

#[derive(Debug, Clone, Copy)]
pub enum SeverityLevel {
    Low,
    Medium,
    High,
    Critical,
}

impl fmt::Display for SeverityLevel {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SeverityLevel::Low => write!(f, "LOW"),
            SeverityLevel::Medium => write!(f, "MEDIUM"),
            SeverityLevel::High => write!(f, "HIGH"),
            SeverityLevel::Critical => write!(f, "CRITICAL"),
        }
    }
}

#[derive(Debug)]
pub struct AnomalyEvidence {
    pub field: String,
    pub value: String,
    pub expected: Option<String>,
    pub explanation: String,
}

impl AnomalyReport {
    pub fn new(
        vessel: Option<Vessel>,
        anomaly_type: AnomalyType,
        severity: SeverityLevel,
        description: String,
        evidence: Vec<AnomalyEvidence>,
        timestamp: DateTime<Utc>,
    ) -> Self {
        AnomalyReport {
            vessel,
            anomaly_type,
            severity,
            description,
            evidence,
            timestamp,
        }
    }

    pub fn get_score(&self) -> u8 {
        match self.severity {
            SeverityLevel::Low => 25,
            SeverityLevel::Medium => 50,
            SeverityLevel::High => 75,
            SeverityLevel::Critical => 100,
        }
    }

    pub fn is_significant(&self) -> bool {
        self.severity >= SeverityLevel::Medium || !self.evidence.is_empty()
    }
}

// ============================================================================
// RESOLVER ENGINE
// ============================================================================

#[derive(Debug)]
pub struct ResolverConfig {
    pub cache_ttl: Duration,
    pub anomaly_detection_enabled: bool,
    pub max_vessels_in_memory: usize,
}

impl Default for ResolverConfig {
    fn default() -> Self {
        ResolverConfig {
            cache_ttl: config::DEFAULT_CACHE_TTL,
            anomaly_detection_enabled: true,
            max_vessels_in_memory: 100_000,
        }
    }
}

pub struct VesselResolver {
    db: RegistryDatabase,
    config: ResolverConfig,
    vessels_cache: IndexMap<u64, Vessel>,
    recent_messages: Vec<AisMessage>,
    anomaly_history: HashMap<u64, Vec<AnomalyReport>>,
}

impl Default for VesselResolver {
    fn default() -> Self {
        let mut resolver = VesselResolver::new();
        // Pre-populate with some known vessels
        resolver.preload_known_vessels();
        resolver
    }
}

impl VesselResolver {
    pub fn new(config: ResolverConfig) -> Self {
        VesselResolver {
            db: RegistryDatabase::new(),
            config,
            vessels_cache: IndexMap::new(),
            recent_messages: Vec::with_capacity(10_000),
            anomaly_history: HashMap::new(),
        }
    }

    pub fn with_default_config() -> Self {
        let mut resolver = VesselResolver::new();
        resolver.preload_known_vessels();
        resolver
    }

    // Pre-load known vessels from common registries
    fn preload_known_vessels(&mut self) {
        // Add some sample vessels for testing
        let now = Utc::now();
        
        self.add_sample_vessel(
            Mmsi::from_string("371234567").unwrap(),
            "Sample Vessel Alpha".to_string(),
            "US",
            now,
        );
        
        self.add_sample_vessel(
            Mmsi::from_string("371234568").unwrap(),
            "Sample Vessel Beta".to_string(),
            "UK",
            now,
        );
    }

    fn add_sample_vessel(&mut self, mmsi: Mmsi, name: String, flag: &str, timestamp: DateTime<Utc>) {
        let registry = self.db.get_registry(flag).unwrap_or(&RegistryInfo::default());
        
        let vessel = Vessel::new(
            mmsi,
            name.clone(),
            flag.to_string(),
            registry.clone(),
            2018,
            5_000.0,
            120.0,
            20.0,
        );

        self.vessels_cache.insert(mmsi.value, vessel);
    }

    pub fn resolve(&self, mmsi: u64) -> Result<Option<Vessel>, ResolverError> {
        if let Some(vessel) = self.vessels_cache.get(&mmsi) {
            return Ok(Some(vessel.clone()));
        }

        // Try to extract flag from MMSI prefix (simplified)
        let prefix_byte = ((mmsi >> 24) & 0xFF) as u8;
        
        // Simple mapping - in production this would use a proper database
        let flag_map: &[(&u8, &str)] = &[
            (&16, "US"),
            (&37, "UK"),
            (&50, "DE"),
            (&49, "FR"),
            (&20, "NL"),
            (&44, "NO"),
            (&48, "JP"),
            (&47