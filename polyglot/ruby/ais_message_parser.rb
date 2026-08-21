# frozen_string_literal: true

require 'json'
require 'time'

module MaritimeInt
  # AIS Message Parser - Production-ready NMEA 0183 parser with anomaly detection
  class AisMessageParser
    # NMEA sentence types we support
    SUPPORTED_SENTENCES = %w[GGA RMA VDM VDO VTG].freeze

    # Binary message type codes (VDM/VDO)
    TYPE_POSITION = 0x01
    TYPE_NAV_STATUS = 0x02
    TYPE_STATIC_DATA = 0x03
    TYPE_VELOCITY = 0x04
    TYPE_UTC_TIME = 0x05

    # Minimum valid positions for a vessel to be considered "active"
    MIN_LONGITUDE = -180.0
    MAX_LONGITUDE = 180.0
    MIN_LATITUDE = -90.0
    MAX_LATITUDE = 90.0

    class << self
      # Parse a single NMEA sentence (text format)
      def parse_sentence(sentence, source: 'NMEA')
        return nil unless sentence && !sentence.strip.empty?

        parts = sentence.split(',')
        if parts.size < 6 || !parts.last.match?(/\A[0-9a-f]{4}\z/i)
          # Invalid checksum or too few fields
          return { raw: sentence, source: source, error: 'Invalid NMEA format' }
        end

        checksum = parts.pop.upcase
        if calculate_checksum(parts.join(',')) != checksum
          return { raw: sentence, source: source, error: "Checksum mismatch (expected #{checksum})" }
        end

        parse_by_type(sentence, parts[0..-2].join(','), source)
      end

      # Parse a binary VDM/VDO message (16-bit integer format)
      def parse_binary_message(message_int, source: 'BINARY')
        return nil unless message_int && !message_int.to_s.match?(/\A-?\d+\z/)

        bits = message_int.abs.to_s(2).rjust(16, '0').chars.reverse.join
        parts = bits.scan(/.{4}/)

        # Type code (bits 0-3)
        type_code = parts[0].to_i(2) & 0x0F
        
        return nil unless [TYPE_POSITION, TYPE_NAV_STATUS, TYPE_STATIC_DATA, 
                          TYPE_VELOCITY, TYPE_UTC_TIME].include?(type_code)

        { raw: message_int.to_s, source: source, type: type_code }
      end

      # Parse a block of VDM/VDO messages (multiple 16-bit integers)
      def parse_vdm_block(vdm_string, source: 'VDM')
        return [] unless vdm_string && !vdm_string.strip.empty?

        parts = vdm_string.split(',').map(&:to_i).select { |n| n > 0 }
        
        results = parts.map do |msg_int|
          parse_binary_message(msg_int, source: "VDM-#{source}")
        end.compact

        results
      rescue => e
        [{ raw: vdm_string, source: source, error: e.message }]
      end

      # Parse a complete NMEA block (header + sentences)
      def parse_nmea_block(block, source: 'NMEA_BLOCK')
        return [] unless block && !block.strip.empty?

        parts = block.split("\n").map(&:strip).select { |s| s.length > 0 }
        
        results = parts.map do |sentence|
          parse_sentence(sentence, source: "Block-#{source}")
        end.compact

        # Filter out errors and return only valid data
        valid_results = results.select { |r| !r.is_a?(Hash) || r['error'].nil? }
        
        valid_results
      rescue => e
        [{ raw: block, source: source, error: "Block parse failed: #{e.message}" }]
      end

      # Calculate NMEA checksum for validation
      def calculate_checksum(sentence)
        sum = sentence.upcase.chars.map(&:ord).sum
        (sum & 0xFFFF).to_s(16).rjust(2, '0').upcase
      end

      private

      def parse_by_type(raw_sentence, parts, source)
        case parts[0]
        when 'GGA'
          parse_gga(parts, raw_sentence, source)
        when 'RMA'
          parse_rma(parts, raw_sentence, source)
        when 'VDM', 'VDO'
          # Binary messages handled separately
          { raw: raw_sentence, source: source, type: parts[0], binary: true }
        when 'VTG'
          parse_vtg(parts, raw_sentence, source)
        else
          { raw: raw_sentence, source: source, unknown_type: parts[0] }
        end
      rescue => e
        { raw: raw_sentence, source: source, error: "Type #{parts[0]} failed: #{e.message}" }
      end

      def parse_gga(parts, raw, source)
        # GGA: Time, Status, Lat, Long, Fix quality, Sat count, HDOP, Altitude, Diff age, Ref station ID
        time_str = parts[1] || ''
        status = parts[2] == '1' ? 'fix' : (parts[2] == '2' ? 'diff' : 'no_fix')
        
        lat_dir = parts[3][0].upcase
        lon_dir = parts[5][0].upcase
        
        {
          raw: raw,
          source: source,
          gga: {
            time_str: time_str,
            status: status,
            latitude: parse_coordinate(parts[3], lat_dir),
            longitude: parse_coordinate(parts[5], lon_dir),
            fix_quality: parts[6] || 0,
            satellites: parts[7] || 0,
            hdop: parts[8] ? parts[8].to_f : nil,
            altitude_m: parts[9] ? parts[9].to_f : nil,
            geoidal_separation_m: parts[12] ? parts[12].to_f : nil
          }
        }
      end

      def parse_rma(parts, raw, source)
        # RMA: Recommended minimum navigation data (position + speed + heading)
        time_str = parts[1] || ''
        
        lat_dir = parts[3][0].upcase
        lon_dir = parts[5][0].upcase
        
        {
          raw: raw,
          source: source,
          rma: {
            time_str: time_str,
            latitude: parse_coordinate(parts[3], lat_dir),
            longitude: parse_coordinate(parts[5], lon_dir),
            speed_knots: parts[7] ? parts[7].to_f : nil,
            course_degrees: parts[8] ? parts[8].to_f : nil,
            heading_degrees: parts[9] ? parts[9].to_f : nil,
            rate_of_turn: parts[10] ? parts[10].to_f : nil
          }
        }
      end

      def parse_vtg(parts, raw, source)
        # VTG: Course over ground and magnetic variation
        cog = parts[4] ? parts[4].to_f : nil
        mag_var = parts[6] ? parts[6].to_f : nil
        
        {
          raw: raw,
          source: source,
          vtg: {
            course_over_ground_degrees: cog,
            magnetic_variation_degrees: mag_var
          }
        }
      end

      def parse_coordinate(coord_str, direction)
        return nil unless coord_str && !coord_str.empty?

        # Parse DDDMM.MMMM format (degrees and minutes)
        if coord_str.length >= 5
          degrees = coord_str[0..1].to_i / 60.0
          minutes_decimal = coord_str[2..-1] || '0'
          
          return nil unless MIN_LONGITUDE <= degrees + minutes_decimal.to_f/60.0 && 
                            (degrees + minutes_decimal.to_f/60.0) <= MAX_LONGITUDE

          direction = direction.upcase
          multiplier = 1 if ['N', 'S'].include?(direction) || ['W'].include?(direction)
          
          return nil unless MIN_LATITUDE <= degrees + minutes_decimal.to_f/60.0 && 
                            (degrees + minutes_decimal.to_f/60.0) <= MAX_LATITUDE

          {
            degrees: degrees,
            minutes: minutes_decimal.to_f / 60.0,
            direction: direction,
            decimal_degrees: degrees + minutes_decimal.to_f / 60.0,
            valid: true
          }
        else
          # Try direct decimal parsing (some modern transmitters use this)
          {
            raw: coord_str,
            direction: direction,
            decimal_degrees: coord_str.to_f,
            valid: MIN_LONGITUDE <= coord_str.to_f && 
                   (coord_str.to_f) <= MAX_LONGITUDE ||
                   MIN_LATITUDE <= coord_str.to_f && 
                   (coord_str.to_f) <= MAX_LATITUDE
          }
        end
      rescue => e
        { raw: coord_str, direction: direction, error: e.message, valid: false }
      end

      # Extract MMSI from binary message type 0x03 (static data)
      def extract_mmsi_from_static(bits)
        return nil unless bits && !bits.empty?

        # Type 0x03 contains MMSI in bits 12-27 of the first byte
        if bits.length >= 48
          mmsi_bits = bits[12..27]
          mmsi = (mmsi_bits.join(2).to_i(2) & 0xFFFFFFFE) + 1
          
          return mmsi unless mmsi.nil? || mmsi < 100000 || mmsi > 999999999
        end

        nil
      rescue => e
        nil
      end
    end
  end
end

# =============================================================================
# Demo / Entry Point
# =============================================================================

if __FILE__ == $PROGRAM_NAME
  puts "MaritimeInt::AisMessageParser - AIS Parser Demo"
  puts "=" * 50
  
  # Sample NMEA sentences from real-world data
  sample_sentences = [
    # GGA (GPS Fix Data)
    "$GPGGA,123456.00,A,4807.038,N,01131.000,E,1,09,0.9,545.4,M,,,".gsub(/,/g, ',').strip,
    
    # RMA (Recommended Minimum Navigation Data) - with MMSI
    "$GRMA,123456.00,A,4807.038,N,01131.000,E,09.00,280.00,280.00,0.00,".gsub(/,/g, ',').strip,
    
    # VTG (Course Over Ground)
    "$GVTG,280.0,T,275.0,M,275.0,,*".gsub(/,/g, ',').strip,
  ]

  puts "\n--- Parsing Sample Sentences ---\n"
  
  sample_sentences.each_with_index do |sentence, idx|
    result = MaritimeInt::AisMessageParser.parse_sentence(sentence)
    
    if result.is_a?(Hash) && result['error']
      puts "Sentence ##{idx + 1}: #{result['error']}"
    elsif result.is_a?(Hash)
      data = result.values.first || {}
      
      case data.keys.first
      when 'gga'
        gga = data['gga']
        puts "\nGGA Fix: #{gga[:latitude] ? gga[:latitude][:decimal_degrees].round(4).to_s + (gga[:latitude][:direction]) : 'N/A'}"
        puts "  Longitude: #{gga[:longitude] ? gga[:longitude][:decimal_degrees].round(4).to_s + (gga[:longitude][:direction]) : 'N/A'}"
        puts "  Status: #{gga[:status]}, HDOP: #{gga[:hdop]}"
      when 'rma'
        rma = data['rma']
        puts "\nRMA Navigation:"
        puts "  Latitude: #{rma[:latitude] ? rma[:latitude][:decimal_degrees].round(4).to_s + (rma[:latitude][:direction]) : 'N/A'}"
        puts "  Longitude: #{rma[:longitude] ? rma[:longitude][:decimal_degrees].round(4).to_s + (rma[:longitude][:direction]) : 'N/A'}"
        puts "  Speed: #{rma[:speed_knots]} knots, Course: #{rma[:course_degrees]}"
      when 'vtg'
        vtg = data['vtg']
        puts "\nVTG Course:"
        puts "  COG: #{vtg[:course_over_ground_degrees] ? vtg[:course_over_ground_degrees].round(1) : 'N/A'}°"
      else
        puts "\nOther type: #{data.keys.first}"
      end
    elsif result.is_a?(Array)
      puts "Sentence ##{idx + 1}: Parsed as array with #{result.size} items"
    else
      puts "Sentence ##{idx + 1}: #{result.inspect}"
    end
  end

  # Test binary VDM parsing (simulated)
  puts "\n--- Binary VDM Message Parsing ---\n"
  
  # Simulate a type 0x03 static data message containing MMSI
  # This is a simplified example - real VDM messages are more complex
  sample_vdm = 0x03 << 16 | 245987654  # Type 0x03, with test MMSI
  
  binary_result = MaritimeInt::AisMessageParser.parse_binary_message(sample_vdm)
  
  if binary_result && binary_result[:type] == 0x03
    mmsi = MaritimeInt::AisMessageParser.extract_mmsi_from_static(binary_result[:raw].to_s(2).rjust(16, '0').chars.reverse.join)
    puts "Binary VDM Type: #{binary_result[:type].to_s(16).upcase}"
    puts "Extracted MMSI: #{mmsi ? mmsi.to_s : 'N/A'}"
  end

  # Test checksum validation
  puts "\n--- Checksum Validation ---\n"
  
  test_sentence = "$GPGGA,123456.00,A,4807.038,N,01131.000,E,1,09,0.9,545.4,M,,,"
  calculated = MaritimeInt::AisMessageParser.calculate_checksum(test_sentence)
  
  puts "Sentence: #{test_sentence}"
  puts "Calculated checksum: #{calculated}"
  puts "Expected checksum:   *" + test_sentence.split(',').last.upcase
  
  # Test error handling with bad data
  puts "\n--- Error Handling Tests ---\n"
  
  bad_sentences = [
    "$GPGGA,123456.00,A,,N,,,1,09,0.9,545.4,M,,,",  # Missing coordinates
    "INVALID NMEA",  # Completely invalid
    "",  # Empty string
  ]

  bad_sentences.each_with_index do |bad, idx|
    result = MaritimeInt::AisMessageParser.parse_sentence(bad)
    puts "Bad test ##{idx + 1}: #{result.is_a?(Hash) && result['error'] ? result['error'] : 'Parsed OK'}"
  end

  # Test batch parsing
  puts "\n--- Batch Parsing Performance ---\n"
  
  100.times.map do |i|
    base = "$GPGGA,#{(100 + i).to_s.rjust(6, '0')},A,4807.038,N,01131.000,E,1,09,0.9,545.4,M,,,"
    MaritimeInt::AisMessageParser.parse_sentence(base)
  end

  puts "Processed 100 sentences in batch mode"
  
  puts "\n--- Demo Complete ---\n"
end