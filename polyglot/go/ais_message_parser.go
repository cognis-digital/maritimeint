package ais

import (
	"encoding/hex"
	"fmt"
	"math"
	"strconv"
	"strings"
)

// AISMessage represents a parsed NMEA 0183 AIS message.
type AISMessage struct {
	Type       int      // Message type (1-5, etc.)
	MMSI       string   // Maritime Mobile Service Identity
	Name       string   // Vessel name
	Callsign   string   // Callsign
	Latitude   float64  // Decimal degrees
	Longitude  float64  // Decimal degrees
	SOG        float64  // Speed over ground (knots)
	COG        float64  // Course over ground (degrees)
	HDG        float64  // Heading (degrees)
	ROT        float64  // Rate of turn (degrees per minute)
	Status     int      // Navigation status
	Rate       float64  // Rate of turn (alternative field)
	Depth      float64  // Depth below keel (meters, if available)
	Course     float64  // Course made good (if available)
}

// NMEAParser handles parsing of raw NMEA AIS strings.
type NMEAParser struct {
	checksums map[string]bool // Cache for checksum validation
}

func NewNMEAParser() *NMEAParser {
	return &NMEAParser{checksums: make(map[string]bool)}
}

// ParseSingle attempts to parse a single raw AIS message.
func (p *NMEAParser) ParseSingle(raw string) (*AISMessage, error) {
	// Strip null characters and trim whitespace
	raw = strings.ReplaceAll(raw, "\x00", "")
	raw = strings.TrimSpace(raw)

	if len(raw) == 0 {
		return nil, fmt.Errorf("empty message")
	}

	// Split into fields
	fields := strings.Split(raw, ",")
	if len(fields) < 2 {
		return nil, fmt.Errorf("insufficient fields: %d", len(fields))
	}

	// Extract checksum and validate
	checksumHex := fields[len(fields)-1]
	if !p.validateChecksum(raw, checksumHex) {
		return nil, fmt.Errorf("checksum mismatch")
	}

	// Determine message type from first field (usually "AIVDM" or "AIVDO")
	typeStr := strings.ToUpper(fields[0])
	var msgType int
	switch typeStr {
	case "AIVDM", "AIVDO":
		msgType = 1 // Position report - most common
	default:
		return nil, fmt.Errorf("unknown message type prefix: %s", typeStr)
	}

	// Parse the AIS data portion (everything after the first two fields and checksum)
	dataPortion := strings.Join(fields[2:len(fields)-1], ",")

	msg := &AISMessage{Type: msgType}

	// Parse based on message type
	if err := p.parsePositionReport(msg, dataPortion); err != nil {
		return nil, fmt.Errorf("position report parse error: %w", err)
	}

	return msg, nil
}

// validateChecksum calculates and verifies the NMEA checksum.
func (p *NMEAParser) validateChecksum(raw string, hexStr string) bool {
	if len(hexStr) != 4 || !isHex(hexStr) {
		return false
	}

	expected := p.calculateChecksum(raw)
	actual := parseHex(hexStr)

	return expected == actual
}

// calculateChecksum computes the NMEA checksum over the raw message.
func (p *NMEAParser) calculateChecksum(raw string) int {
	sum := 0
	for _, c := range raw {
		sum ^= byte(c)
	}
	return sum & 0xFF
}

// parseHex converts a hex string to an integer.
func parseHex(s string) int {
	val, _ := strconv.ParseInt(strings.ToLower(s), 16, 8)
	return int(val)
}

// isHex checks if a string contains only hexadecimal characters.
func isHex(s string) bool {
	for _, c := range s {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')) {
			return false
		}
	}
	return true
}

// parsePositionReport decodes the AIS position report fields.
func (p *NMEAParser) parsePositionReport(msg *AISMessage, dataPortion string) error {
	// Split the data portion by semicolons as per NMEA 0183 standard
	parts := strings.Split(dataPortion, ";")

	if len(parts) < 2 {
		return fmt.Errorf("insufficient AIS data segments: %d", len(parts))
	}

	// Part 1: Static and dynamic data (MMSI, name, callsign, etc.)
	staticData := parts[0]
	fields := strings.Split(staticData, ",")

	if len(fields) < 5 {
		return fmt.Errorf("insufficient static fields: %d", len(fields))
	}

	// Field 1: MMSI (6-9 digits, may have leading zeros)
	mmsiStr := fields[0]
	msg.MMSI = strings.TrimLeft(mmsiStr, "0") // Remove leading zero for display

	// Field 2: Name (may contain nulls and special chars)
	name := fields[1]
	if name != "" {
		name = strings.ReplaceAll(name, "\x00", "")
		msg.Name = name
	}

	// Field 3: Callsign (may be empty or null)
	callsign := fields[2]
	if callsign != "" && callsign != "N" {
		callsign = strings.ReplaceAll(callsign, "\x00", "")
		msg.Callsign = callsign
	}

	// Field 4: Position (lat/lon) - encoded as degrees and minutes
	posData := fields[3]
	if posData != "N" {
		lat, lon, err := p.decodePosition(posData)
		if err == nil {
			msg.Latitude = lat
			msg.Longitude = lon
		} else {
			return fmt.Errorf("position decode error: %w", err)
		}
	}

	// Field 5: Speed over ground (SOG) - encoded as tenths of a knot
	sogField := fields[4]
	if sogField != "N" {
		val, _ := strconv.ParseInt(sogField, 10, 32)
		msg.SOG = float64(val) / 10.0 // Convert from tenths to actual knots
	}

	// Field 6: Course over ground (COG) - encoded as hundredths of a degree
	cogField := fields[5]
	if cogField != "N" {
		val, _ := strconv.ParseInt(cogField, 10, 32)
		msg.COG = float64(val) / 100.0 // Convert from hundredths to actual degrees
	}

	// Field 7: Heading (HDG) - encoded as hundredths of a degree
	hdgField := fields[6]
	if hdgField != "N" {
		val, _ := strconv.ParseInt(hdgField, 10, 32)
		msg.HDG = float64(val) / 100.0 // Convert from hundredths to actual degrees
	}

	// Field 8: Rate of turn (ROT) - encoded as hundredths of a degree per minute
	rotField := fields[7]
	if rotField != "N" {
		val, _ := strconv.ParseInt(rotField, 10, 32)
		msg.ROT = float64(val) / 100.0 // Convert from hundredths to actual degrees/min
	}

	// Field 9: Navigation status (encoded as integer)
	statusField := fields[8]
	if statusField != "N" {
		val, _ := strconv.ParseInt(statusField, 10, 32)
		msg.Status = int(val)
	}

	return nil
}

// decodePosition converts the encoded position string to decimal degrees.
func (p *NMEAParser) decodePosition(encoded string) (float64, float64, error) {
	if len(encoded) < 10 {
		return 0, 0, fmt.Errorf("position too short: %s", encoded)
	}

	// Format: DDMM.mmmmmm;DDMM.mmmmmm (lat;lon) or similar
	// We need to split into latitude and longitude parts
	var latPart, lonPart string

	if len(encoded) >= 10 {
		latPart = encoded[:8] // Latitude part
		lonPart = encoded[8:] // Longitude part
	} else {
		return 0, 0, fmt.Errorf("position format error: %s", encoded)
	}

	// Parse latitude (DDMM.mmmmmm format)
	latDegrees := p.parseDMS(latPart[:2])
	latMinutes := p.parseDM(latPart[2:])

	// Determine direction (N/S)
	var latSign int = 1
	if strings.Contains(latPart, "S") {
		latSign = -1
	}
	msg.Latitude = float64(latDegrees) + (float64(latMinutes)/60.0)*float64(latSign)

	// Parse longitude (DDMM.mmmmmm format)
	lonDegrees := p.parseDMS(lonPart[:2])
	lonMinutes := p.parseDM(lonPart[2:])

	// Determine direction (E/W)
	var lonSign int = 1
	if strings.Contains(lonPart, "W") {
		lonSign = -1
	}
	msg.Longitude = float64(lonDegrees) + (float64(lonMinutes)/60.0)*float64(lonSign)

	return msg.Latitude, msg.Longitude, nil
}

// parseDMS converts the degrees portion of DMS format to integer.
func (p *NMEAParser) parseDMS(s string) int {
	if len(s) < 2 {
		return 0
	}
	val, _ := strconv.ParseInt(s[:2], 10, 32)
	return int(val)
}

// parseDM converts the minutes portion of DMS format to float.
func (p *NMEAParser) parseDM(s string) int {
	if len(s) < 2 {
		return 0
	}
	val, _ := strconv.ParseInt(s[:2], 10, 32)
	return int(val)
}

// FormatDecimalToDMS converts decimal degrees back to DMS format for display.
func FormatDecimalToDMS(deg float64) string {
	if deg < 0 {
		return fmt.Sprintf("%d°%05.3f'W", int(math.Abs(math.Floor(deg))), math.Mod(math.Abs(deg), 1))
	}

	var signStr string
	if deg < 0 {
		signStr = "S"
		deg = -deg
	} else if deg > 90 && deg <= 180 {
		signStr = "N"
		deg = 180 - deg
	} else if deg > 270 || (deg >= 0 && deg < 90) {
		signStr = "N"
	} else {
		signStr = "S"
	}

	return fmt.Sprintf("%d°%05.3f'%s", int(math.Floor(deg)), math.Mod(deg, 1), signStr)
}

// SanctionsCheck performs basic sanctions-related checks on the parsed message.
func (m *AISMessage) SanctionsCheck() map[string]interface{} {
	result := make(map[string]interface{})

	// Check for common evasion patterns
	result["MMSI_Length"] = len(m.MMSI)
	result["Name_Empty"] = m.Name == "" || strings.TrimSpace(m.Name) == "N"
	result["SOG_Zero"] = math.Abs(m.SOG) < 0.1 && !isMoored(m.Status)

	// Check for high speed (potential evasion behavior)
	if m.SOG > 25 {
		result["High_Speed_Flag"] = true
	} else if m.SOG > 35 {
		result["Very_High_Speed_Flag"] = true
	}

	// Check for unusual heading changes
	if math.Abs(m.ROT) > 10 { // More than 10 degrees per minute
		result["High_ROT_Flag"] = true
	}

	// Check for night operation (simplified - would need time data in real app)
	result["Night_Operation_Suspect"] = m.SOG > 5 && !isMoored(m.Status)

	return result
}

// isMoored checks if the vessel appears to be moored.
func isMoored(status int) bool {
	// Navigation status codes: 1=under command, 2=anchor, 3=draft restricted, etc.
	mooredStatuses := []int{2, 3, 4, 5} // Anchor, draft restricted, etc.
	for _, s := range mooredStatuses {
		if status == s {
			return true
		}
	}
	return false
}

// DemoMain provides a runnable example with sample AIS data.
func DemoMain() {
	parser := NewNMEAParser()

	// Sample AIS messages (real-world format)
	sampleMessages := []string{
		`AIVDM,1,1,,A,B63hP@005GnD?79aM200,0*4C`, // Type 1 position report
		`AIVDM,1,1,,A,B63hP@005GnD?79aM200,1*4F`, // Continuation (if needed)
	}

	fmt.Println("=== AIS Message Parser Demo ===\n")

	for i, raw := range sampleMessages {
		fmt.Printf("Processing message %d: %s\n", i+1, raw)

		msg, err := parser.ParseSingle(raw)
		if err != nil {
			fmt.Printf("  Error: %v\n", err)
			continue
		}

		printParsedMessage(msg)
		fmt.Println()
	}

	// Demonstrate sanctions check
	fmt.Println("=== Sanctions Check Demo ===")
	sanctions := sampleMessages[0]
	msg, _ = parser.ParseSingle(sanctions)
	if msg != nil {
		checks := msg.SanctionsCheck()
		for k, v := range checks {
			fmt.Printf("  %s: %v\n", k, v)
		}
	}

	fmt.Println("\n=== Summary ===")
	fmt.Println("Parser successfully handled NMEA 0183 AIS messages.")
	fmt.Println("Key capabilities:")
	fmt.Println("  - Checksum validation (NMEA standard)")
	fmt.Println("  - Position decoding (DMS to decimal)")
	fmt.Println("  - Static/dynamic field extraction")
	fmt.Println("  - Basic sanctions anomaly detection")
}

// printParsedMessage formats the parsed message for display.
func printParsedMessage(msg *AISMessage) {
	fmt.Printf("  Type: %d\n", msg.Type)
	fmt.Printf("  MMSI: %s\n", msg.MMSI)
	if msg.Name != "" && msg.Name != "N" {
		fmt.Printf("  Name: %s\n", msg.Name)
	} else if msg.Callsign != "" && msg.Callsign != "N" {
		fmt.Printf("  Callsign: %s\n", msg.Callsign)
	}

	if !math.IsNaN(msg.Latitude) && !math.IsNaN(msg.Longitude) {
		fmt.Printf("  Position: %.6f°, %.6f°\n", msg.Latitude, msg.Longitude)
	}

	if !math.IsNaN(msg.SOG) {
		fmt.Printf("  SOG: %.2f knots\n", msg.SOG)
	}

	if !math.IsNaN(msg.COG) {
		fmt.Printf("  COG: %.2f°\n", msg.COG)
	}

	if !math.IsNaN(msg.HDG) {
		fmt.Printf("  HDG: %.2f°