use std::fmt;
use std::str::FromStr;

/// AIS NMEA 0183 message types supported
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum AisMessageType {
    Type1,   // Basic position/speed/course
    Type2,   // Extended (same as type 1 with more data)
    Type3,   // Static data (MMSI, name, dimensions)
    Type4,   // Dynamic data
    Type5,   // Static + dynamic combined
    Type6,   // Position only
    Type7,   // Extended position
    Type8,   // Static + extended position
    Type9,   // Static + dynamic + extended position
}

impl AisMessageType {
    pub fn from_byte(byte: u8) -> Self {
        match byte {
            1 => AisMessageType::Type1,
            2 => AisMessageType::Type2,
            3 => AisMessageType::Type3,
            4 => AisMessageType::Type4,
            5 => AisMessageType::Type5,
            6 => AisMessageType::Type6,
            7 => AisMessageType::Type7,
            8 => AisMessageType::Type8,
            9 => AisMessageType::Type9,
            _ => AisMessageType::Type1, // Default to type 1 for unknown types
        }
    }

    pub fn from_nmea_type(nmea_type: u8) -> Self {
        match nmea_type {
            0x01 | 0x21 => AisMessageType::Type1,
            0x02 | 0x22 => AisMessageType::Type2,
            0x03 | 0x23 => AisMessageType::Type3,
            0x04 | 0x24 => AisMessageType::Type4,
            0x05 | 0x25 => AisMessageType::Type5,
            0x06 | 0x26 => AisMessageType::Type6,
            0x07 | 0x27 => AisMessageType::Type7,
            0x08 | 0x28 => AisMessageType::Type8,
            0x09 | 0x29 => AisMessageType::Type9,
            _ => AisMessageType::Type1,
        }
    }
}

impl fmt::Display for AisMessageType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AisMessageType::Type1 => write!(f, "Type 1 (Basic)"),
            AisMessageType::Type2 => write!(f, "Type 2 (Extended)"),
            AisMessageType::Type3 => write!(f, "Type 3 (Static)"),
            AisMessageType::Type4 => write!(f, "Type 4 (Dynamic)"),
            AisMessageType::Type5 => write!(f, "Type 5 (Static+Dynamic)"),
            AisMessageType::Type6 => write!(f, "Type 6 (Position)"),
            AisMessageType::Type7 => write!(f, "Type 7 (Extended Position)"),
            AisMessageType::Type8 => write!(f, "Type 8 (Static+Ext. Position)"),
            AisMessageType::Type9 => write!(f, "Type 9 (Full)"),
        }
    }
}

/// Parse error types for AIS messages
#[derive(Debug)]
pub enum ParseError {
    EmptyMessage(String),
    InvalidFieldIndex(usize),
    InvalidCoordinate(f64),
    InvalidSpeed(u32),
    InvalidCourse(u16),
    InvalidMmsi(String),
    UnknownMessageType(u8),
    ChecksumMismatch,
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseError::EmptyMessage(msg) => write!(f, "Empty or malformed message: {}", msg),
            ParseError::InvalidFieldIndex(idx) => write!(f, "Invalid field index: {}", idx),
            ParseError::InvalidCoordinate(coord) => write!(f, "Invalid coordinate: {}", coord),
            ParseError::InvalidSpeed(speed) => write!(f, "Invalid speed: {}", speed),
            ParseError::InvalidCourse(course) => write!(f, "Invalid course: {}", course),
            ParseError::InvalidMmsi(mmsi) => write!(f, "Invalid MMSI: {}", mmsi),
            ParseError::UnknownMessageType(ty) => write!(f, "Unknown message type: 0x{:02X}", ty),
            ParseError::ChecksumMismatch => write!(f, "NMEA checksum mismatch"),
        }
    }
}

impl std::error::Error for ParseError {}

/// Result type alias for AIS parsing operations
pub type AisResult<T> = Result<T, ParseError>;

/// Represents a parsed AIS message with all extracted data
#[derive(Debug)]
pub struct ParsedAisMessage {
    pub raw: String,
    pub nmea_type: u8,
    pub ais_type: AisMessageType,
    
    // Static/Identity Data
    pub mmsi: Option<u32>,
    pub name: Option<String>,
    pub call_sign: Option<String>,
    pub ship_type_code: Option<u8>,
    pub length_meters: Option<f64>,
    pub width_meters: Option<f64>,
    
    // Position Data
    pub latitude: Option<f64>,
    pub longitude: Option<f64>,
    pub position_accuracy: Option<u8>,
    pub rate_of_turn: Option<i16>,
    pub heading: Option<u16>,
    pub true_heading: Option<u16>,
    
    // Dynamic Data
    pub speed_over_ground_knots: Option<f32>,
    pub course_over_ground_degrees: Option<u16>,
    pub second_rate_of_turn: Option<i16>,
    pub draft_meters: Option<f32>,
    pub destination_port_code: Option<String>,
    pub draught_reference_datum: Option<u8>,
    
    // Quality flags
    pub position_quality: u8,
    pub rate_of_turn_quality: u8,
    pub heading_quality: u8,
}

impl ParsedAisMessage {
    /// Create a new parsed message from raw NMEA string
    pub fn parse(raw: &str) -> AisResult<Self> {
        if raw.trim().is_empty() {
            return Err(ParseError::EmptyMessage(raw.to_string()));
        }

        // Split by comma - NMEA format uses commas as field separators
        let fields: Vec<&str> = raw.split(',').collect();
        
        if fields.is_empty() || fields[0].trim().is_empty() {
            return Err(ParseError::EmptyMessage(raw.to_string()));
        }

        // Parse the message type from first field (e.g., "1,234567890.00,-12.3456,..." or "2,234567890,0.00,12.3456,")
        let nmea_type = if let Some(first_field) = fields.get(0) {
            // Extract the type byte (first character after any leading spaces)
            first_field.trim().chars().next()
                .map(|c| c.to_digit(10).unwrap_or(0))
                .unwrap_or(0x21) // Default to Type 5 if unknown format
        } else {
            0x21
        };

        let ais_type = AisMessageType::from_nmea_type(nmea_type);

        // Parse latitude (field 3 in most types, field 4 in type 5+)
        let lat_str = fields.get(3).unwrap_or(&"");
        let latitude = Self::parse_coordinate(lat_str)?;

        // Parse longitude (field 4 or 5 depending on type)
        let lon_str = fields.get(4).unwrap_or(&"");
        let longitude = Self::parse_coordinate(lon_str)?;

        // Parse speed over ground (usually field 6-8)
        let sog_str = fields.get(6).unwrap_or(&"");
        let sog_knots = Self::parse_speed(sog_str)?;

        // Parse course over ground (usually field 7-9)
        let cog_str = fields.get(7).unwrap_or(&"");
        let cog_degrees = Self::parse_course(cog_str)?;

        // Parse heading (field 8-10 in most types)
        let hdg_str = fields.get(8).unwrap_or(&"");
        let heading = Self::parse_heading(hdg_str)?;

        // Parse rate of turn (field 9-11)
        let rot_str = fields.get(9).unwrap_or(&"");
        let rot_degrees = Self::parse_rate_of_turn(rot_str)?;

        // Parse MMSI - this varies by type, try to find it
        let mmsi = Self::extract_mmsi(&fields);

        // Build the result with partial data (safe defaults for missing fields)
        Ok(ParsedAisMessage {
            raw: raw.to_string(),
            nmea_type,
            ais_type,
            latitude: Some(latitude),
            longitude: Some(longitude),
            speed_over_ground_knots: Some(sog_knots),
            course_over_ground_degrees: Some(cog_degrees),
            heading: Some(heading),
            rate_of_turn: Some(rot_degrees),
            mmsi,
            name: None, // Would require Type 3/5/8/9 parsing
            call_sign: None,
            ship_type_code: None,
            length_meters: None,
            width_meters: None,
            position_accuracy: None,
            true_heading: None,
            second_rate_of_turn: None,
            draft_meters: None,
            destination_port_code: None,
            draught_reference_datum: None,
            position_quality: 0,
            rate_of_turn_quality: 0,
            heading_quality: 0,
        })
    }

    /// Parse a coordinate string (DDMM.MMMM or DD.DDDDDD format)
    fn parse_coordinate(s: &str) -> AisResult<f64> {
        let s = s.trim();
        
        if s.is_empty() || s.len() < 2 {
            return Err(ParseError::InvalidCoordinate(0.0));
        }

        // Handle both formats: DDMM.MMMM and DD.DDDDDD
        let (degrees, minutes) = match s.chars().count() {
            9..=13 => {
                // Format: DDMM.MMMM or DDDM.MMMM
                if s.len() == 9 || s.len() == 10 {
                    // DDMM.MMMM format
                    let parts: Vec<&str> = s.split('.').collect();
                    match parts.as_slice() {
                        [deg_min, frac] => {
                            let deg_min = deg_min.parse::<f64>()?;
                            let frac = frac.parse::<f64>().unwrap_or(0.0);
                            
                            // Convert to decimal degrees
                            let result = if s.len() == 9 {
                                // DDMM.MMMM - 2 digits for degrees
                                deg_min / 100.0 + (frac * 0.001) / 60.0
                            } else {
                                // DDDM.MMMM - 3 digits for degrees
                                deg_min / 1000.0 + (frac * 0.001) / 60.0
                            };
                            
                            // Determine hemisphere
                            let sign = if s[0] == 'N' || s[0] == '+' { 1.0 } else { -1.0 };
                            Ok(result * sign)
                        },
                        _ => Err(ParseError::InvalidCoordinate(0.0)),
                    }
                } else {
                    // DD.DDDDDD format (9 digits total = 2 deg + 6 decimal min)
                    let parts: Vec<&str> = s.split('.').collect();
                    match parts.as_slice() {
                        [deg, frac] => {
                            let degrees = deg.parse::<f64>()?;
                            let minutes_decimal = frac.parse::<f64>().unwrap_or(0.0);
                            
                            // Convert to decimal degrees
                            let result = if s.len() == 9 {
                                // DD.DDDDDD - 2 digits for degrees
                                degrees + (minutes_decimal / 100000.0) / 60.0
                            } else {
                                // DDD.DDDDDD - 3 digits for degrees  
                                degrees + (minutes_decimal / 1000000.0) / 60.0
                            };
                            
                            let sign = if s[0] == 'N' || s[0] == '+' { 1.0 } else { -1.0 };
                            Ok(result * sign)
                        },
                        _ => Err(ParseError::InvalidCoordinate(0.0)),
                    }
                }
            },
            7..=9 => {
                // Format: DDD.DDDDDD (3 digits for degrees, 6 decimal min)
                let parts: Vec<&str> = s.split('.').collect();
                match parts.as_slice() {
                    [deg, frac] => {
                        let degrees = deg.parse::<f64>()?;
                        let minutes_decimal = frac.parse::<f64>().unwrap_or(0.0);
                        
                        // Convert to decimal degrees
                        let result = if s.len() == 9 {
                            // DDD.DDDDDD - 3 digits for degrees
                            degrees + (minutes_decimal / 1000000.0) / 60.0
                        } else {
                            // DD.DDDDDD - 2 digits for degrees
                            degrees + (minutes_decimal / 100000.0) / 60.0
                        };
                        
                        let sign = if s[0] == 'N' || s[0] == '+' { 1.0 } else { -1.0 };
                        Ok(result * sign)
                    },
                    _ => Err(ParseError::InvalidCoordinate(0.0)),
                }
            },
            _ => Err(ParseError::InvalidCoordinate(0.0)),
        }?;

        // Clamp to valid range (-90 to +90 for lat, -180 to +180 for lon)
        let result = if s.len() == 7 || (s.len() > 7 && s.chars().nth(2).unwrap_or(' ')) != 'D' {
            // Latitude: should be within ±90
            degrees.max(-90.0).min(90.0)
        } else {
            // Longitude: should be within ±180
            degrees.max(-180.0).min(180.0)
        };

        Ok(result)
    }

    /// Parse speed in knots (3 decimal places = 0.1 knot resolution)
    fn parse_speed(s: &str) -> AisResult<f32> {
        let s = s.trim();
        
        if s.is_empty() || s.len() < 4 {
            return Err(ParseError::InvalidSpeed(0));
        }

        // Format: XXXX.XXX (4 digits integer + 3 decimal = 1 knot resolution)
        let parts: Vec<&str> = s.split('.').collect();
        
        match parts.as_slice() {
            [int_part, frac_part] => {
                let int_val = int_part.parse::<u32>()?;
                let frac_val = frac_part.parse::<f32>().unwrap_or(0.0);
                
                // 3 decimal places = 0.1 knot resolution
                let speed = (int_val as f32) + (frac_val / 1000.0);
                
                Ok(speed.max(0.0))
            },
            _ => Err(ParseError::InvalidSpeed(0)),
        }
    }

    /// Parse course