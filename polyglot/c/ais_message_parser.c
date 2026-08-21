/*
 * maritimeint/polyglot/c/ais_message_parser.c
 * 
 * Complete AIS Message Parser with Sanctions Evasion Anomaly Detection
 * 
 * Parses NMEA 0183 AIVDM format messages and extracts vessel data.
 * Includes anomaly detection for potential sanctions evasion patterns.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <ctype.h>

/* Constants */
#define MAX_MMSI_LEN 10
#define MAX_NAME_LEN 256
#define MAX_CALLSIGN_LEN 8
#define MAX_LATITUDE_LEN 30
#define MAX_LONGITUDE_LEN 30
#define MAX_NMEA_LINE 256
#define MAX_VESSEL_COUNT 1024

/* AIS Message Types */
typedef enum {
    MSG_TYPE_1 = 1,      /* Basic ship data - static + dynamic */
    MSG_TYPE_2,          /* Ship static data */
    MSG_TYPE_3,          /* Dynamic data */
    MSG_TYPE_5,          /* Static data (supplemental) */
    MSG_TYPE_6,          /* Static data (supplemental 2) */
    MSG_TYPE_7,          /* Static data (supplemental 3) */
    MSG_TYPE_8,          /* Dynamic data (supplemental) */
    MSG_TYPE_9,          /* Static data (supplemental 4) */
    MSG_TYPE_10,         /* Static data (supplemental 5) */
    MSG_TYPE_12,         /* Position report - static + dynamic */
    MSG_TYPE_18,         /* Extended static data */
    MSG_TYPE_19,         /* Extended dynamic data */
    MSG_TYPE_20,         /* Extended static data (supplemental) */
    MSG_TYPE_21,         /* Extended dynamic data (supplemental) */
    MSG_TYPE_22,         /* Extended static data (supplemental 2) */
    MSG_TYPE_23,         /* Extended dynamic data (supplemental 2) */
    MSG_TYPE_24,         /* Extended static data (supplemental 3) */
    MSG_TYPE_25          /* Extended dynamic data (supplemental 3) */
} AisMessageType;

/* AIS Message Structure - Complete vessel record */
typedef struct {
    int message_id;              /* AIS message type (1-25) */
    char mmsi[MAX_MMSI_LEN];     /* Maritime Mobile Service Identity */
    char name[MAX_NAME_LEN];     /* Vessel name */
    char callsign[MAX_CALLSIGN_LEN]; /* Call sign */
    
    double latitude;             /* Latitude in degrees */
    double longitude;            /* Longitude in degrees */
    double speed_over_ground;    /* Speed over ground (knots) */
    double course_over_ground;   /* Course over ground (degrees, 0-360) */
    double heading;              /* Heading (magnetic, 0-360) */
    double rate_of_turn;         /* Rate of turn (deg/min) */
    
    int navigation_status;       /* 0=underway using engine, etc. */
    int draught;                 /* Draught in meters */
    int year_built;              /* Year built */
    int month_built;             /* Month built */
    int days_since_update;       /* Days since last update */
    
    double accuracy_flag;        /* 0=high, 1=medium, 2=low */
    double raim_flag;            /* 0=no RAIM, 1=RAIM active */
    double ror_flag;             /* Rate of turn flag */
    double cog_flag;             /* Course over ground flag */
    double sog_flag;             /* Speed over ground flag */
    
    int is_valid;                /* Overall message validity */
    int has_position;            /* Has valid position data */
    int has_speed;               /* Has speed data */
} AisMessage;

/* Anomaly Flags for Sanctions Evasion Detection */
typedef enum {
    ANOMALY_NONE = 0,
    ANOMALY_GHOST_VESSEL,        /* Appears/disappears frequently */
    ANOMALY_SPEED_INCONSISTENCY, /* Speed doesn't match course changes */
    ANOMALY_LOW_SPEED_HIGH_TURN, /* Turning at low speed (maneuvering?) */
    ANOMALY_RAPID_POSITION_CHANGE,/* Large position jump without high speed */
    ANOMALY_DRAUGHT_INCONSISTENCY,/* Draught changes oddly */
    ANOMALY_TIME_GAP_LARGE,      /* Long gaps between updates */
    ANOMALY_POSITION_JUMP,        /* Position jumps > 50nm */
    ANOMALY_HEADING_MISMATCH,     /* Heading vs COG mismatch */
    ANOMALY_ALL                  /* All flags set */
} AnomalyFlags;

/* Global state for tracking vessel history */
typedef struct {
    AisMessage current_msg;
    char last_mmsi[MAX_MMSI_LEN];
    double last_lat, last_lon;
    double last_sog;
    double last_cog;
    double last_heading;
    time_t last_update_time;
    int update_count;
    AnomalyFlags anomaly_flags;
} VesselState;

/* Initialize global vessel state array */
static VesselState vessel_states[MAX_VESSEL_COUNT];
static int next_vessel_slot = 0;

/* Helper: Convert degrees to radians */
static inline double deg2rad(double deg) {
    return deg * M_PI / 180.0;
}

/* Helper: Convert radians to degrees */
static inline double rad2deg(double rad) {
    return rad * 180.0 / M_PI;
}

/* Helper: Normalize angle to 0-360 range */
static inline double normalize_angle(double angle) {
    while (angle < 0) angle += 360.0;
    while (angle >= 360.0) angle -= 360.0;
    return angle;
}

/* Helper: Calculate great circle distance between two positions */
static inline double calc_distance(double lat1, double lon1, 
                                    double lat2, double lon2) {
    double dlat = deg2rad(lat2 - lat1);
    double dlon = deg2rad(lon2 - lon1);
    
    double a = sin(dlat/2.0)*sin(dlat/2.0) +
               cos(deg2rad(lat1))*cos(deg2rad(lat2)) *
               sin(dlon/2.0)*sin(dlon/2.0);
    
    double c = 2.0 * atan2(sqrt(a), sqrt(1.0 - a));
    
    /* Earth radius in nautical miles */
    return 3440.065 * c;
}

/* Helper: Parse MMSI (remove leading zeros, validate) */
static void parse_mmsi(const char *src, char *dest, int max_len) {
    int i = 0, j = 0;
    
    /* Skip leading $AIVDM or similar prefixes if present */
    while (*src && !isdigit(*src)) src++;
    
    /* Extract numeric MMSI portion */
    while (isdigit(*src) && j < max_len - 1) {
        dest[j++] = *src;
        src++;
    }
    dest[j] = '\0';
}

/* Helper: Parse latitude from NMEA format (DD.DDDDDD) */
static double parse_latitude(const char *src) {
    if (!src || !*src) return 0.0;
    
    int is_north = 1;
    double lat_deg, lat_min, lat_sec;
    
    /* Check for S suffix */
    if (strchr(src, 'S')) {
        is_north = 0;
    } else if (strchr(src, 'N')) {
        is_north = 1;
    }
    
    /* Remove direction letter for parsing */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && !isalpha(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    /* Parse DDD.DDDDDD format */
    char *dot = strchr(clean, '.');
    if (!dot) return 0.0;
    
    double degrees = atof(clean);
    lat_deg = (int)(degrees / 100.0);
    double fraction = fmod(degrees, 100.0);
    lat_min = (int)(fraction * 100.0);
    lat_sec = (fraction - lat_min/100.0) * 10000.0;
    
    /* Convert to decimal degrees */
    double result = lat_deg + lat_min/60.0 + lat_sec/3600.0;
    
    return is_north ? result : -result;
}

/* Helper: Parse longitude from NMEA format (DDD.DDDDDD) */
static double parse_longitude(const char *src) {
    if (!src || !*src) return 0.0;
    
    int is_east = 1;
    double lon_deg, lon_min, lon_sec;
    
    /* Check for W suffix */
    if (strchr(src, 'W')) {
        is_east = 0;
    } else if (strchr(src, 'E')) {
        is_east = 1;
    }
    
    /* Remove direction letter for parsing */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && !isalpha(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    /* Parse DDD.DDDDDD format */
    char *dot = strchr(clean, '.');
    if (!dot) return 0.0;
    
    double degrees = atof(clean);
    lon_deg = (int)(degrees / 100.0);
    double fraction = fmod(degrees, 100.0);
    lon_min = (int)(fraction * 100.0);
    lon_sec = (fraction - lon_min/100.0) * 10000.0;
    
    /* Convert to decimal degrees */
    double result = lon_deg + lon_min/60.0 + lon_sec/3600.0;
    
    return is_east ? result : -result;
}

/* Helper: Parse speed over ground (knots) */
static double parse_speed(const char *src) {
    if (!src || !*src) return 0.0;
    
    /* Remove any trailing flags or letters */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && isdigit(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    return atof(clean);
}

/* Helper: Parse course over ground */
static double parse_course(const char *src) {
    if (!src || !*src) return 0.0;
    
    /* Remove trailing flags or letters */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && isdigit(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    return atof(clean);
}

/* Helper: Parse heading */
static double parse_heading(const char *src) {
    if (!src || !*src) return 0.0;
    
    /* Remove trailing flags or letters */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && isdigit(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    return atof(clean);
}

/* Helper: Parse rate of turn */
static double parse_rot(const char *src) {
    if (!src || !*src) return 0.0;
    
    /* Remove trailing flags or letters */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && isdigit(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    return atof(clean);
}

/* Helper: Parse navigation status */
static int parse_nav_status(const char *src) {
    if (!src || !*src) return 0;
    
    /* Remove trailing flags or letters */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && isdigit(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    return atoi(clean);
}

/* Helper: Parse draught */
static int parse_draught(const char *src) {
    if (!src || !*src) return -1;
    
    /* Remove trailing flags or letters */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && isdigit(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    return atoi(clean);
}

/* Helper: Parse year built */
static int parse_year_built(const char *src) {
    if (!src || !*src) return -1;
    
    /* Remove trailing flags or letters */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && isdigit(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    return atoi(clean);
}

/* Helper: Parse month built */
static int parse_month_built(const char *src) {
    if (!src || !*src) return -1;
    
    /* Remove trailing flags or letters */
    char clean[32];
    int j = 0;
    for (int i = 0; src[i] && isdigit(src[i]); i++) {
        if (j < 31) clean[j++] = src[i];
    }
    clean[j] = '\0';
    
    return atoi(clean);
}

/* Helper: Check if message looks like valid AIVDM */
static int is_valid_aivdm(const char *line) {
    if (!line || !*line) return 0;
    
    /* Must start with $AIVDM or similar */
    const char *prefix = strstr(line, "$AIVDM");
    if (!prefix) prefix = strstr(line, "$AIIVL");
    if (!prefix) prefix = strstr(line, "$GPRMC");
    if (!prefix) return 0;
    
    /* Must have numeric content after prefix */
    const char *num_start = strchr(prefix + 6, '1');
    if (!num_start) num_start = strchr(prefix + 6, '2');
    if (!num_start) return 0;
    
    /* Check for at least some digits */
    int digit_count = 0;
    for (const char *p = num_start; *p && digit_count < 5; p++) {
        if (isdigit(*p)) digit_count++;
    }
    return digit_count > 2;
}

/* Helper: Extract message ID from AIVDM header */
static int extract_msg_id(const char *line) {
    const char *prefix = strstr(line, "$AIVDM");
    if (!prefix) prefix = strstr(line, "$AIIVL");
    if (!prefix) return -1;
    
    /* Find the message ID byte (usually after position fields) */
    int msg_id = 0;
    const char *p