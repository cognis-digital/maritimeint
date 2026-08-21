package polyglot.java;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * AIS Message Parser for maritimeint tool.
 * Parses NMEA 0183 AIVDM format messages containing vessel tracking data.
 */
public class ais_message_parser {

    // Pattern to match AIVDM message structure: $AIVDM,1,2,,A,<data>,*<checksum>
    private static final Pattern AIVDM_PATTERN = Pattern.compile(
        "^\\$AIVDM,(\\d+),(\\w),,([A-Z]),(.*)\\*(\\d+)$"
    );

    // DateTime format for NMEA time (hhmmss.ss)
    private static final DateTimeFormatter TIME_FORMATTER = 
        DateTimeFormatter.ofPattern("HHmmss.SS");

    /**
     * Represents a parsed AIS message.
     */
    public static class AisMessage {
        private int sequence;
        private char status;
        private String data;
        private int checksum;
        private LocalDateTime timestamp;
        private boolean isValid;

        // Parsed fields (may be null if not yet parsed)
        private Mmsi mmsi;
        private Position position;
        private VesselInfo vessel;

        public AisMessage() {}

        public int getSequence() { return sequence; }
        public char getStatus() { return status; }
        public String getData() { return data; }
        public int getChecksum() { return checksum; }
        public LocalDateTime getTimestamp() { return timestamp; }
        public boolean isValid() { return isValid; }

        public Mmsi getMmsi() { return mmsi; }
        public Position getPosition() { return position; }
        public VesselInfo getVessel() { return vessel; }

        public void setSequence(int seq) { this.sequence = seq; }
        public void setStatus(char s) { this.status = s; }
        public void setData(String d) { this.data = d; }
        public void setChecksum(int c) { this.checksum = c; }
        public void setTimestamp(LocalDateTime t) { this.timestamp = t; }
        public void setIsValid(boolean v) { this.isValid = v; }

        public void setMmsi(Mmsi m) { this.mmsi = m; }
        public void setPosition(Position p) { this.position = p; }
        public void setVessel(VesselInfo v) { this.vessel = v; }

        @Override
        public String toString() {
            return "AisMessage{" +
                   "sequence=" + sequence +
                   ", status='" + status + '\'' +
                   ", data='" + data + '\'' +
                   ", checksum=" + checksum +
                   ", timestamp=" + timestamp +
                   ", isValid=" + isValid +
                   ", mmsi=" + (mmsi != null ? mmsi.toString() : "null") +
                   ", position=" + (position != null ? position.toString() : "null") +
                   '}';
        }
    }

    /**
     * Represents a Maritime Identification Distinguishing Number.
     */
    public static class Mmsi {
        private int value;
        private String raw;

        public Mmsi(int v) { this.value = v; this.raw = Integer.toString(v); }
        public Mmsi(String r, int v) { this.raw = r; this.value = v; }

        @Override
        public String toString() { return "MMSI: " + raw; }
    }

    /**
     * Represents a geographic position.
     */
    public static class Position {
        private double latitude;
        private char latHemisphere; // N or S
        private double longitude;
        private char lonHemisphere; // E or W

        public Position() {}

        @Override
        public String toString() {
            return "Position{" +
                   "lat=" + (latitude >= 0 ? "+" : "") + latitude + 
                   latHemisphere + ", " +
                   "lon=" + (longitude >= 0 ? "+" : "") + longitude +
                   lonHemisphere + "}";
        }

        public double getLatitude() { return latitude; }
        public char getLatHemisphere() { return latHemisphere; }
        public double getLongitude() { return longitude; }
        public char getLonHemisphere() { return lonHemisphere; }
    }

    /**
     * Represents vessel-specific information.
     */
    public static class VesselInfo {
        private String mmsi;
        private String name;
        private double speedOverGround; // knots
        private double courseOverGround; // degrees
        private double heading; // degrees (magnetic)
        private boolean inPort;

        public VesselInfo() {}

        @Override
        public String toString() {
            return "Vessel{" +
                   "name='" + name + '\'' +
                   ", sog=" + speedOverGround + " kn" +
                   ", cog=" + courseOverGround + "°" +
                   ", heading=" + heading + "°" +
                   ", inPort=" + inPort + "}";
        }

        public String getMmsi() { return mmsi; }
        public String getName() { return name; }
        public double getSpeedOverGround() { return speedOverGround; }
        public double getCourseOverGround() { return courseOverGround; }
        public double getHeading() { return heading; }
        public boolean isInPort() { return inPort; }

        public void setMmsi(String m) { this.mmsi = m; }
        public void setName(String n) { this.name = n; }
        public void setSpeedOverGround(double s) { this.speedOverGround = s; }
        public void setCourseOverGround(double c) { this.courseOverGround = c; }
        public void setHeading(double h) { this.heading = h; }
        public void setInPort(boolean p) { this.inPort = p; }
    }

    /**
     * Parses a single AIVDM message into structured data.
     */
    public static AisMessage parse(String nmeaLine) {
        if (nmeaLine == null || !nmeaLine.startsWith("$AIVDM")) {
            return new AisMessage();
        }

        Matcher matcher = AIVDM_PATTERN.matcher(nmeaLine);
        if (!matcher.matches()) {
            return new AisMessage();
        }

        AisMessage msg = new AisMessage();
        msg.setSequence(Integer.parseInt(matcher.group(1)));
        msg.setStatus(matcher.group(2).charAt(0));
        msg.setData(matcher.group(4));
        msg.setChecksum(Integer.parseInt(matcher.group(5)));

        // Decode the base64-like data portion
        String decoded = decodeAivdmData(msg.getData());
        if (decoded == null) {
            msg.setIsValid(false);
            return msg;
        }

        try {
            parseAisFields(decoded, msg);
            msg.setIsValid(true);
        } catch (Exception e) {
            // Log or handle parsing error
            msg.setIsValid(false);
        }

        return msg;
    }

    /**
     * Decodes the AIVDM data portion from base64-like encoding.
     */
    private static String decodeAivdmData(String data) {
        if (data == null || data.isEmpty()) {
            return null;
        }

        // Remove any trailing checksum marker if present
        int asteriskIndex = data.lastIndexOf('*');
        if (asteriskIndex > 0 && Character.isDigit(data.charAt(asteriskIndex + 1))) {
            data = data.substring(0, asteriskIndex);
        }

        // Split into chunks of 6 characters (each represents 3 bits)
        List<Integer> bitChunks = new ArrayList<>();
        
        for (int i = 0; i < data.length() - 1; i += 6) {
            String chunk = data.substring(i, Math.min(i + 6, data.length()));
            
            // Convert 6-char base64-like to integer
            int value = 0;
            for (int j = 0; j < 6 && j < chunk.length(); j++) {
                char c = chunk.charAt(j);
                if (c >= 'A' && c <= 'Z') {
                    value += (c - 'A' + 1) << ((5 - j) * 3);
                } else if (c == '-') {
                    // Special character for 0-7 range
                    value += (c - '-' + 8) << ((5 - j) * 3);
                }
            }
            
            bitChunks.add(value & 0x1F); // Keep only lower 5 bits
        }

        if (bitChunks.isEmpty()) {
            return null;
        }

        // Combine all chunks into a single long
        long combined = 0;
        for (int chunk : bitChunks) {
            combined = (combined << 5) | chunk;
        }

        return Long.toString(combined);
    }

    /**
     * Parses the decoded AIVDM fields.
     */
    private static void parseAisFields(String decoded, AisMessage msg) throws Exception {
        // Format: [flags][mmsi][position][time][speed/course][heading][etc]
        
        String[] parts = decoded.split("\\|");
        if (parts.length < 2) {
            return;
        }

        // Part 0: Flags and other metadata
        int flags = Integer.parseInt(parts[0]);
        
        // Part 1: MMSI
        if (parts[1] != null && !parts[1].isEmpty()) {
            msg.setMmsi(new Mmsi(parts[1]));
        }

        // Parts 2-3: Position data
        if (parts.length > 2) {
            String latPart = parts[2];
            String lonPart = parts[3];

            if (latPart != null && !latPart.isEmpty()) {
                double latitude = parseLatitude(latPart);
                msg.setPosition(new Position());
                msg.getPosition().setLatitude(latitude);
                
                // Determine hemisphere from flags or default to N
                char latHemisphere = getLatHemisphere(flags, 1);
                if (latHemisphere == 'S') {
                    latitude = -latitude;
                }
                msg.getPosition().setLatHemisphere(latHemisphere);

                // Convert from degrees*100000 to actual degrees
                latitude /= 100000.0;
            }

            if (lonPart != null && !lonPart.isEmpty()) {
                double longitude = parseLongitude(lonPart);
                msg.getPosition().setLongitude(longitude);
                
                // Determine hemisphere from flags or default to E
                char lonHemisphere = getLonHemisphere(flags, 1);
                if (lonHemisphere == 'W') {
                    longitude = -longitude;
                }
                msg.getPosition().setLonHemisphere(lonHemisphere);

                // Convert from degrees*100000 to actual degrees
                longitude /= 100000.0;
            }
        }

        // Part 4: Time (hhmmss.ss)
        if (parts.length > 4 && parts[4] != null && !parts[4].isEmpty()) {
            try {
                String timeStr = parts[4];
                // Remove decimal point for parsing, then add it back
                int dotIndex = timeStr.indexOf('.');
                String timeNoDec = dotIndex > 0 ? 
                    timeStr.substring(0, dotIndex) : timeStr;
                
                int hours = Integer.parseInt(timeNoDec.substring(0, 2));
                int minutes = Integer.parseInt(timeNoDec.substring(2, 4));
                int seconds = Integer.parseInt(dotIndex > 0 ? 
                    timeStr.substring(5, 7) : "00");

                msg.setTimestamp(LocalDateTime.of(
                    LocalDateTime.now().getYear(),
                    LocalDateTime.now().getMonthValue(),
                    LocalDateTime.now().getDayOfMonth(),
                    hours, minutes, seconds));
            } catch (Exception e) {
                // Time parsing failed
            }
        }

        // Part 5: Speed over ground and course over ground
        if (parts.length > 5 && parts[5] != null && !parts[5].isEmpty()) {
            try {
                String[] speedCourse = parts[5].split(",");
                
                double sog = Double.parseDouble(speedCourse[0]); // knots
                msg.getVessel().setSpeedOverGround(sog);

                if (speedCourse.length > 1) {
                    double cog = Double.parseDouble(speedCourse[1]); // degrees
                    msg.getVessel().setCourseOverGround(cog);
                }
            } catch (Exception e) {
                // Speed/course parsing failed
            }
        }

        // Part 6: Heading (magnetic)
        if (parts.length > 6 && parts[6] != null && !parts[6].isEmpty()) {
            try {
                double heading = Double.parseDouble(parts[6]);
                msg.getVessel().setHeading(heading);
            } catch (Exception e) {
                // Heading parsing failed
            }
        }

        // Part 7: In port flag
        if (parts.length > 7 && parts[7] != null && !parts[7].isEmpty()) {
            msg.getVessel().setInPort("1".equals(parts[7]));
        }
    }

    /**
     * Parses latitude from AIVDM format.
     */
    private static double parseLatitude(String latPart) {
        if (latPart == null || latPart.isEmpty()) {
            return 0.0;
        }

        // Latitude is stored as degrees*100000, with special handling for N/S
        try {
            String clean = latPart.replace("N", "").replace("S", "");
            double degs = Double.parseDouble(clean) / 100000.0;
            
            // Handle the special case where first digit indicates hemisphere
            if (degs < 90 && degs > -90) {
                return degs;
            } else {
                // Adjust for proper range
                return Math.abs(degs) % 180.0;
            }
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }

    /**
     * Parses longitude from AIVDM format.
     */
    private static double parseLongitude(String lonPart) {
        if (lonPart == null || lonPart.isEmpty()) {
            return 0.0;
        }

        try {
            String clean = lonPart.replace("E", "").replace("W", "");
            double degs = Double.parseDouble(clean) / 100000.0;
            
            // Handle the special case where first digit indicates hemisphere
            if (degs < 180 && degs > -180) {
                return degs;
            } else {
                // Adjust for proper range
                return Math.abs(degs) % 360.0;
            }
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }

    /**
     * Gets latitude hemisphere from flags.
     */
    private static char getLatHemisphere(int flags, int position) {
        // Default to North if unknown
        return 'N';
    }

    /**
     * Gets longitude hemisphere from flags.
     */
    private static char getLonHemisphere(int flags, int position) {
        // Default to East if unknown
        return 'E';
    }

    /**
     * Main demo/entry point showing parser usage.
     */
    public static void main(String[] args) throws IOException {
        System.out.println("=== AIS Message Parser Demo ===\n");

        // Sample AIVDM messages for testing
        String[] sampleMessages = {
            "$AIVDM,1,1,,A,13wPqer>02p4=5@00a<578,0*6C",
            "$AIVDM,1,1,,B,13wPqer>02p4=5@00a<578,0*6C"
        };

        // Process each message