#include <iostream>
#include <string>
#include <vector>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <cstring>

namespace maritimeint {

// Special values indicating null/unknown data
constexpr double NULL_COORD = 0.0;
constexpr int   NULL_SPEED  = 99;
constexpr int   NULL_COG    = 255;
constexpr char* NULL_STRING = "NULL";

struct VesselData {
    std::string mmsi;          // Maritime Mobile Service Identity
    double      latitude;      // Degrees (DDMM.MMMM format)
    double      longitude;     // Degrees (DDDMM.MMMM format)
    int         speed_over_ground;   // Knots
    int         course_over_ground;  // Degrees
    int         rudder_angle;      // Degrees
    int         heading;           // Degrees
    double      draught;          // Meters
    std::string vessel_name;     // Ship name
    int         message_type;     // AIS Type (1,2,3,4)
    bool        valid_checksum;  // Checksum validation result
};

// Convert DDMM.MMMM to decimal degrees
double ddmm_to_decimal(double ddmm) {
    if (ddmm == NULL_COORD || std::isnan(ddmm)) return 0.0;
    
    int deg = static_cast<int>(std::abs(ddmm));
    double min_frac = ddmm - deg;
    double minutes = min_frac * 10000;
    double decimal_deg = deg + (minutes / 60.0);
    
    // Handle negative coordinates (West/South)
    if (ddmm < 0) {
        return -decimal_deg;
    }
    return decimal_deg;
}

// Convert DDDMM.MMMM to decimal degrees
double dddmm_to_decimal(double dddmm) {
    if (dddmm == NULL_COORD || std::isnan(dddmm)) return 0.0;
    
    int deg = static_cast<int>(std::abs(dddmm));
    double min_frac = dddmm - deg;
    double minutes = min_frac * 10000;
    double decimal_deg = deg + (minutes / 60.0);
    
    if (dddmm < 0) {
        return -decimal_deg;
    }
    return decimal_deg;
}

// Validate NMEA checksum
bool validate_checksum(const std::string& sentence, int& error_code) {
    // Remove leading/trailing whitespace and carriage returns
    size_t start = sentence.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return false;
    
    size_t end = sentence.find_last_not_of(" \t\r\n") + 1;
    std::string clean = sentence.substr(start, end - start);
    
    // Check for *hh checksum format
    auto asterisk_pos = clean.find('*');
    if (asterisk_pos == std::string::npos) {
        error_code = 0; // No checksum present
        return false;
    }
    
    std::string data_part = clean.substr(0, asterisk_pos);
    std::string check_part = clean.substr(asterisk_pos + 1);
    
    // Calculate expected checksum
    unsigned char sum = 0;
    for (char c : data_part) {
        sum ^= static_cast<unsigned char>(c);
    }
    
    if (check_part.length() < 2) return false;
    
    int received = (static_cast<int>(check_part[0]) * 16) + 
                   static_cast<int>(check_part[1]);
    
    error_code = (sum == static_cast<unsigned char>(received)) ? 0 : 1;
    return error_code == 0;
}

// Extract field from NMEA sentence by index
std::string extract_field(const std::string& sentence, int field_index) {
    if (field_index < 0 || field_index >= static_cast<int>(sentence.size())) {
        return "";
    }
    
    size_t start = 0;
    for (int i = 0; i <= field_index && start != std::string::npos; ++i) {
        if (start == std::string::npos) {
            start = sentence.find_first_of(",");
            if (start == std::string::npos || start > sentence.size()) break;
            start++;
        } else {
            size_t comma_pos = sentence.find_first_of(",", start);
            if (comma_pos != std::string::npos) {
                start = comma_pos + 1;
            } else {
                start = sentence.size();
            }
        }
    }
    
    // Find end of field (next comma or end of string)
    size_t end = sentence.find_first_of(",", start);
    if (end == std::string::npos || end > sentence.size()) {
        end = sentence.size();
    }
    
    return sentence.substr(start, end - start);
}

// Parse a single AIS message into VesselData
VesselData parse_ais_message(const std::string& nmea_sentence) {
    VesselData result;
    int error_code = 0;
    
    // Validate checksum first
    if (!validate_checksum(nmea_sentence, error_code)) {
        result.valid_checksum = false;
        return result;
    }
    result.valid_checksum = true;
    
    // Extract MMSI (field 1)
    std::string mmsi_str = extract_field(nmea_sentence, 0);
    if (!mmsi_str.empty()) {
        result.mmsi = mmsi_str;
    }
    
    // Determine message type from field 2 and 3
    int msg_type_raw = std::stoi(extract_field(nmea_sentence, 1));
    int pos_type_raw = std::stoi(extract_field(nmea_sentence, 2));
    
    if (msg_type_raw == 0) {
        result.message_type = 1; // Type 1: Position report
    } else if (msg_type_raw == 1) {
        result.message_type = 2; // Type 2: Extended position report
    } else if (msg_type_raw == 2) {
        result.message_type = 3; // Type 3: Same as Type 1/2
    } else if (msg_type_raw == 3) {
        result.message_type = 4; // Type 4: Extended position report
    } else {
        result.message_type = msg_type_raw;
    }
    
    // Parse latitude and longitude based on message type
    double lat_str, lon_str;
    int start_lat = 0, end_lat = 0, start_lon = 0, end_lon = 0;
    
    if (result.message_type == 1) {
        // Type 1: DDMM.MMMM DDDMM.MMMM
        start_lat = 3; end_lat = 8;
        start_lon = 9; end_lon = 14;
    } else if (result.message_type == 2 || result.message_type == 3) {
        // Type 2/3: DDMM.MMMM DDDMM.MMMM
        start_lat = 3; end_lat = 8;
        start_lon = 9; end_lon = 14;
    } else if (result.message_type == 4) {
        // Type 4: DDMM.MMMM DDDMM.MMMM
        start_lat = 3; end_lat = 8;
        start_lon = 9; end_lon = 14;
    }
    
    result.latitude = ddmm_to_decimal(std::stod(nmea_sentence.substr(start_lat, end_lat - start_lat)));
    result.longitude = dddmm_to_decimal(std::stod(nmea_sentence.substr(start_lon, end_lon - start_lon)));
    
    // Parse speed over ground (field 5)
    int sog_raw = std::stoi(extract_field(nmea_sentence, 4));
    if (sog_raw == NULL_SPEED || sog_raw > 99) {
        result.speed_over_ground = 0;
    } else {
        result.speed_over_ground = sog_raw;
    }
    
    // Parse course over ground (field 6)
    int cog_raw = std::stoi(extract_field(nmea_sentence, 5));
    if (cog_raw == NULL_COG || cog_raw > 359) {
        result.course_over_ground = 0;
    } else {
        result.course_over_ground = cog_raw;
    }
    
    // Parse rudder angle (field 7)
    int rudder_raw = std::stoi(extract_field(nmea_sentence, 6));
    if (rudder_raw == NULL_COG || rudder_raw > 359) {
        result.rudder_angle = 0;
    } else {
        result.rudder_angle = rudder_raw;
    }
    
    // Parse heading (field 8)
    int heading_raw = std::stoi(extract_field(nmea_sentence, 7));
    if (heading_raw == NULL_COG || heading_raw > 359) {
        result.heading = 0;
    } else {
        result.heading = heading_raw;
    }
    
    // Parse draught (field 9)
    double draught_str = std::stod(extract_field(nmea_sentence, 8));
    if (draught_str == NULL_COORD || draught_str > 10.0) {
        result.draught = 0.0;
    } else {
        result.draught = draught_str;
    }
    
    // Parse vessel name (field 10)
    std::string name_raw = extract_field(nmea_sentence, 9);
    if (!name_raw.empty()) {
        result.vessel_name = name_raw;
    }
    
    return result;
}

// Process a batch of AIS messages
std::vector<VesselData> parse_ais_batch(const std::string& nmea_data) {
    std::vector<VesselData> vessels;
    
    // Split into individual sentences (handle newlines/carriage returns)
    std::istringstream iss(nmea_data);
    std::string sentence;
    
    while (std::getline(iss, sentence)) {
        if (!sentence.empty()) {
            VesselData vessel = parse_ais_message(sentence);
            vessels.push_back(vessel);
        }
    }
    
    return vessels;
}

// Format and print a single vessel record
void print_vessel(const VesselData& v) {
    std::cout << "  MMSI:   " << (v.mmsi.empty() ? "(null)" : v.mmsi) << "\n";
    std::cout << "  Type:   " << v.message_type << "\n";
    std::cout << "  Valid:  " << (v.valid_checksum ? "yes" : "no") << "\n";
    std::cout << "  Lat:    " << std::fixed << std::setprecision(4) 
              << ddmm_to_decimal(v.latitude) << "°\n";
    std::cout << "  Lon:    " << std::fixed << std::setprecision(4) 
              << dddmm_to_decimal(v.longitude) << "°\n";
    std::cout << "  SOG:    " << v.speed_over_ground << " kn\n";
    std::cout << "  COG:    " << v.course_over_ground << "°\n";
    std::cout << "  Heading:" << (v.heading > 0 ? " " : "") << v.heading << "°\n";
    std::cout << "  Draught:" << (v.draught > 0 ? " " : "") << v.draught << " m\n";
    std::cout << "  Name:   " << (v.vessel_name.empty() ? "(null)" : v.vessel_name) << "\n";
}

// Format and print a batch of vessels
void print_vessels(const std::vector<VesselData>& vessels) {
    if (vessels.empty()) {
        std::cout << "  No valid AIS messages found.\n";
        return;
    }
    
    std::cout << "Found " << vessels.size() << " message(s):\n\n";
    for (size_t i = 0; i < vessels.size(); ++i) {
        print_vessel(vessels[i]);
        if (i < vessels.size() - 1) {
            std::cout << "\n---\n";
        }
    }
}

// Simple demo with sample AIS data
int main() {
    // Sample NMEA sentences from real AIS traffic
    const char* sample_data = 
        "240376,1,A,09A8D5,0.00,00.00,00B,C,01,01,03,00,00,00,00,00,00,"
        "240376,1,A,09A8D5,0.00,00.00,00B,C,01,01,03,00,00,00,00,00,00,"
        "240376,1,A,09A8D5,0.00,00.00,00B,C,01,01,03,00,00,00,00,00,00";

    std::cout << "=== MaritimeInt AIS Parser Demo ===\n\n";
    
    auto vessels = parse_ais_batch(sample_data);
    
    print_vessels(vessels);
    
    // Verify checksum validation worked
    std::cout << "\nChecksum Summary:\n";
    for (const auto& v : vessels) {
        std::cout << "  MMSI " << v.mmsi << ": " 
                  << (v.valid_checksum ? "PASS" : "FAIL") << "\n";
    }
    
    return 0;
}

} // namespace maritimeint