// polyglot/typescript/ais_message_parser.ts

import { VesselState } from './vessel_state';

/**
 * AIS Message Parser - Production-grade NMEA 0183 parser for maritimeint
 */

export namespace AisParser {
  // ============================================================================
  // CONSTANTS & CONFIGURATION
  // ============================================================================

  const SATELLITE_SENTINEL_MMSI = 367329500;
  
  const DEFAULT_PORT = 8814;
  
  const MAX_MESSAGE_LENGTH = 256;
  
  const CHECKSUM_MULTIPLIER = 0x10000;

  // ============================================================================
  // TYPE DEFINITIONS
  // ============================================================================

  export interface ParsedMessage {
    raw: string;
    type: MessageType;
    checksumValid: boolean;
    timestamp?: number;
    fields: Record<string, any>;
    errors: string[];
    warnings: string[];
  }

  export interface MessageType {
    name: string;
    description: string;
    class: 'A' | 'B';
    types: number[];
  }

  // ============================================================================
  // MESSAGE TYPE ENUMERATIONS
  // ============================================================================

  enum MessageType {
    CLASS_A_POSITION = 'CLASS_A_POSITION',           // Types 1, 2, 3, 4
    CLASS_A_STATIC = 'CLASS_A_STATIC',               // Type 5
    CLASS_A_VOYAGE = 'CLASS_A_VOYAGE',               // Type 6
    CLASS_A_NAVIGATIONAL_STATUS = 'CLASS_A_NAVIGATIONAL_STATUS', // Type 19
    CLASS_B_POSITION = 'CLASS_B_POSITION',           // Types 7, 8
    CLASS_B_STATIC = 'CLASS_B_STATIC',               // Type 20
    CLASS_B_VOYAGE = 'CLASS_B_VOYAGE',               // Type 21
    CLASS_B_NAVIGATIONAL_STATUS = 'CLASS_B_NAVIGATIONAL_STATUS', // Type 24
    SATELLITE_SENTINEL = 'SATELLITE_SENTINEL',       // Sentinel beacon
    UNKNOWN = 'UNKNOWN'
  }

  export const MESSAGE_TYPES: MessageType[] = [
    { name: 'Position (Class A)', description: 'Real-time position updates', class: 'A', types: [1, 2, 3, 4] },
    { name: 'Static Data (Class A)', description: 'Vessel identity and dimensions', class: 'A', types: [5] },
    { name: 'Voyage Data (Class A)', description: 'Course, speed over ground', class: 'A', types: [6] },
    { name: 'Navigational Status (Class A)', description: 'Turn rate, heading changes', class: 'A', types: [19] },
    { name: 'Position (Class B)', description: 'Simplified position data', class: 'B', types: [7, 8] },
    { name: 'Static Data (Class B)', description: 'Basic vessel info', class: 'B', types: [20] },
    { name: 'Voyage Data (Class B)', description: 'Simplified voyage data', class: 'B', types: [21] },
    { name: 'Navigational Status (Class B)', description: 'Basic navigation status', class: 'B', types: [24] },
    { name: 'Satellite Sentinel', description: 'Beacon for satellite AIS', class: 'A', types: [367329500] }
  ];

  // ============================================================================
  // UTILITY FUNCTIONS
  // ============================================================================

  function calculateChecksum(message: string): number {
    let sum = 0;
    for (let i = 1; i < message.length - 1; i++) {
      const charCode = message.charCodeAt(i);
      sum += charCode;
    }
    return sum % 256;
  }

  function validateChecksum(message: string): boolean {
    if (!message.endsWith('**')) return false;
    
    const content = message.slice(0, -2);
    const receivedChecksum = parseInt(message.slice(-2), 10);
    const calculatedChecksum = calculateChecksum(content);
    
    return calculatedChecksum === receivedChecksum;
  }

  function extractTimestamp(message: string): number | undefined {
    // Format: HHMMSS.CCC (e.g., 123456.789)
    const timestampMatch = message.match(/(\d{2})(\d{2})(\d{2})\.?(\d{2,3})/);
    
    if (!timestampMatch) return undefined;

    const hours = parseInt(timestampMatch[1], 10);
    const minutes = parseInt(timestampMatch[2], 10);
    const seconds = parseFloat(`0.${timestampMatch[4]}`);
    
    // Convert to milliseconds since midnight for easier handling
    return (hours * 3600 + minutes * 60 + seconds) * 1000;
  }

  function extractMMSI(message: string): number | undefined {
    const mmsiMatch = message.match(/(\d{9})/);
    if (!mmsiMatch) return undefined;
    
    // Sentinel beacons have MMSI as part of the timestamp field
    if (parseInt(mmsiMatch[1], 10) === SATELLITE_SENTINEL_MMSI) {
      const tsMatch = message.match(/(\d{2})(\d{2})(\d{2})\.?(\d{2,3})/);
      if (tsMatch) {
        return parseInt(tsMatch[1], 10) * 1000000 + 
               parseInt(tsMatch[2], 10) * 10000 + 
               parseInt(tsMatch[3], 10) * 100;
      }
    }
    
    return parseInt(mmsiMatch[1], 10);
  }

  // ============================================================================
  // PARSER CORE
  // ============================================================================

  export function parseMessage(raw: string): ParsedMessage {
    const errors: string[] = [];
    const warnings: string[] = [];
    
    // Trim and validate basic structure
    raw = raw.trim();
    
    if (raw.length === 0) {
      return {
        raw,
        type: MessageType.UNKNOWN,
        checksumValid: false,
        fields: {},
        errors: ['Empty message'],
        warnings: []
      };
    }

    // Check for proper NMEA format with checksum
    if (!raw.endsWith('**')) {
      errors.push('Missing trailing checksum (**)');
    } else if (!validateChecksum(raw)) {
      errors.push(`Invalid checksum. Expected ${calculateChecksum(raw.slice(0, -2)), got ${parseInt(raw.slice(-2), 10)}`);
    }

    // Extract timestamp
    const timestamp = extractTimestamp(raw);

    // Determine message type and parse fields
    let messageType: MessageType = MessageType.UNKNOWN;
    let parsedFields: Record<string, any> = {};

    // Check for Sentinel beacon first (special case)
    if (raw.includes('367329500')) {
      messageType = MessageType.SATELLITE_SENTINEL;
      parsedFields = extractSentinelData(raw);
    } 
    // Class A messages
    else if (isClassAMessage(raw)) {
      messageType = parseClassA(messageType, raw, errors);
      parsedFields = extractClassAData(raw, messageType);
    } 
    // Class B messages
    else if (isClassBMessage(raw)) {
      messageType = parseClassB(messageType, raw, errors);
      parsedFields = extractClassBData(raw, messageType);
    }

    return {
      raw,
      type: messageType.name,
      checksumValid: !errors.some(e => e.includes('checksum')),
      timestamp,
      fields: parsedFields,
      errors,
      warnings
    };
  }

  // ============================================================================
  // CLASS A PARSING
  // ============================================================================

  function isClassAMessage(message: string): boolean {
    const classATypes = [1, 2, 3, 4, 5, 6, 19];
    return classATypes.some(type => message.includes(`0${type}`) || 
                                      (message.length > 8 && parseInt(message.slice(7), 10) === type));
  }

  function parseClassA(msgType: MessageType, raw: string, errors: string[]): MessageType {
    // Extract Type field from position of first digit after "!"
    const typeMatch = raw.match(/!(\d+)/);
    
    if (typeMatch) {
      const typeNum = parseInt(typeMatch[1], 10);
      
      for (const t of [1, 2, 3, 4, 5, 6, 19]) {
        if (typeNum === t) {
          msgType.types.push(t);
          break;
        }
      }
    }

    return msgType;
  }

  function extractClassAData(raw: string, type: MessageType): Record<string, any> {
    const fields: Record<string, any> = {};

    // Extract MMSI (usually in field 1 after the !)
    const mmsiMatch = raw.match(/!(\d+)/);
    if (mmsiMatch) {
      fields.mmsi = parseInt(mmsiMatch[1], 10);
    }

    // Parse position data based on message type
    switch (type.name) {
      case 'CLASS_A_POSITION':
        return extractPositionData(raw, fields);
      case 'CLASS_A_STATIC':
        return extractStaticData(raw, fields);
      case 'CLASS_A_VOYAGE':
        return extractVoyageData(raw, fields);
      case 'CLASS_A_NAVIGATIONAL_STATUS':
        return extractNavStatusData(raw, fields);
    }

    return fields;
  }

  function extractPositionData(raw: string, baseFields: Record<string, any>): Record<string, any> {
    const posFields = { ...baseFields };

    // Parse position coordinates (usually in field 3-4)
    const coordMatch = raw.match(/!(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})/);

    if (coordMatch) {
      // Format: MMSI HHMMSS.CCC LAT DDMM.CCCC LONG DDDMM.CCCC
      const mmsi = parseInt(coordMatch[1], 10);
      const hours = parseInt(coordMatch[2], 10);
      const minutes = parseInt(coordMatch[3], 10);
      const latDecimals = parseFloat(`0.${coordMatch[4]}`);
      const latSeconds = parseFloat(`0.${coordMatch[6]}`);
      
      posFields.mmsi = mmsi;
      posFields.timestamp = (hours * 3600 + minutes * 60) * 1000;
      
      // Convert DDDMM.CCCC to decimal degrees
      const latDegrees = convertDMS(coordMatch[5], coordMatch[6]);
      posFields.latitude = latDegrees.lat;
      posFields.longitude = latDegrees.lon;
    }

    return posFields;
  }

  function extractStaticData(raw: string, baseFields: Record<string, any>): Record<string, any> {
    const staticFields = { ...baseFields };

    // Parse static data fields (usually in field 5-9)
    const staticMatch = raw.match(/!(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})/);

    if (staticMatch) {
      const mmsi = parseInt(staticMatch[1], 10);
      staticFields.mmsi = mmsi;
      
      // Extract vessel name from field 9-15
      const nameMatch = raw.match(/!(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})/);
      
      if (nameMatch) {
        staticFields.name = nameMatch[11].trim();
      }

      // Extract vessel type from field 16-21
      const typeMatch = raw.match(/!(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})/);
      
      if (typeMatch) {
        staticFields.vesselType = parseInt(typeMatch[12], 10);
      }

      // Extract dimensions from field 22-27
      const dimMatch = raw.match(/!(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})/);
      
      if (dimMatch) {
        staticFields.length = parseFloat(dimMatch[24]) / 100; // Length in meters
        staticFields.width = parseFloat(dimMatch[26]) / 100;   // Width in meters
        staticFields.height = parseFloat(dimMatch[28]);       // Height in meters
      }

      // Extract draught from field 29-34
      const draughtMatch = raw.match(/!(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)/);
      
      if (draughtMatch) {
        staticFields.draught = parseFloat(draughtMatch[34]) / 10; // Draught in meters
      }
    }

    return staticFields;
  }

  function extractVoyageData(raw: string, baseFields: Record<string, any>): Record<string, any> {
    const voyageFields = { ...baseFields };

    // Parse voyage data fields (usually in field 6-10)
    const voyageMatch = raw.match(/!(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)(\d{2})(\d{2})\.(\d{1,3})(\d{2})(\d{2})\.(\d{1,3})([\s\S]{0,50})(\d+)/);

    if (voyageMatch) {
      const mmsi = parseInt(voyageMatch[1], 10);
      voyageFields.mmsi = mmsi;
      
      // Extract course over ground from field 11-16
      const cogMatch = raw.match(/!(\d+)(\d{2})(\