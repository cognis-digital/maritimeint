using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace maritimeint
{
    /// <summary>
    /// AIS Message Parser for vessel tracking and sanctions-evasion anomaly detection.
    /// </summary>
    public static class AisMessageParser
    {
        // NMEA 0183 sentence types we support
        private const string TYPE_GGA = "GGA";
        private const string TYPE_RMC = "RMC";
        private const string TYPE_VTG = "VTG";
        private const string TYPE_ZDA = "ZDA";

        // Default thresholds for anomaly detection (configurable)
        public static double PositionJumpThresholdMeters { get; set; } = 50.0;
        public static double MaxSpeedKnots { get; set; } = 45.0;
        public static double MinSpeedKnots { get; set; } = 0.1;

        /// <summary>
        /// Entry point for demonstration and testing.
        /// </summary>
        public static void Main(string[] args)
        {
            Console.WriteLine("=== AIS Message Parser & Anomaly Detector ===\n");

            // Sample NMEA sentences (real-world examples)
            var sampleSentences = new List<string>
            {
                // GGA - GPS Fix Data
                "GGA,GPS,123456A,,,29.0000,N,081.0000,W,1,12,1.0,29.0,M,07.0,M,,*4E",
                // RMC - Recommended Minimum Specific GPS Data
                "RMC,123456A,,,29.0000,N,081.0000,W,085.5,29.0,A,123456,,*7C",
                // VTG - Course over ground and ground speed
                "VTG,085.5,T,085.5,M,07.0,N,07.0,K,A*7A"
            };

            var parser = new AisParser();
            var vesselTracker = new VesselTracker();

            foreach (var sentence in sampleSentences)
            {
                Console.WriteLine($"Parsing: {sentence}");
                
                var fix = parser.ParseGga(sentence);
                if (fix != null)
                {
                    Console.WriteLine($"  GGA Fix: Lat={fix.Latitude}, Lon={fix.Longitude}, Time={fix.Time}, Quality={fix.Quality}");
                    
                    // Track the vessel position for anomaly detection
                    var record = new PositionRecord
                    {
                        Timestamp = fix.Timestamp,
                        Latitude = fix.Latitude,
                        Longitude = fix.Longitude,
                        SpeedKnots = 0.0,
                        CourseDegrees = 0.0
                    };

                    vesselTracker.TrackPosition(record);
                }

                var rmc = parser.ParseRmc(sentence);
                if (rmc != null)
                {
                    Console.WriteLine($"  RMC: MMSI={rmc.Mmsi}, Name=\"{rmc.Name}\", Speed={rmc.SpeedKnots} kn, Course={rmc.CourseDegrees}°");
                    
                    // Update vessel tracker with velocity data
                    if (rmc.Latitude != null && rmc.Longitude != null)
                    {
                        var record = new PositionRecord
                        {
                            Timestamp = rmc.Timestamp,
                            Latitude = rmc.Latitude.Value,
                            Longitude = rmc.Longitude.Value,
                            SpeedKnots = rmc.SpeedKnots,
                            CourseDegrees = rmc.CourseDegrees
                        };

                        vesselTracker.TrackPosition(record);
                    }
                }

                var vtg = parser.ParseVtg(sentence);
                if (vtg != null)
                {
                    Console.WriteLine($"  VTG: COG={vtg.CourseOverGround}°, SOG={vtg.SpeedKnots} kn");
                    
                    // Update with course/speed data
                    if (rmc?.Latitude != null && rmc.Longitude != null)
                    {
                        var record = new PositionRecord
                        {
                            Timestamp = rmc.Timestamp,
                            Latitude = rmc.Latitude.Value,
                            Longitude = rm