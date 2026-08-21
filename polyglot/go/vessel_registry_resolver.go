package vessel_registry_resolver

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"
)

// Registry represents a flag state with reputation data
type Registry struct {
	CountryCode string `json:"country_code"`
	Name        string `json:"name"`
	Type        string `json:"type"` // "flag_state", "port_state_control", "shell"
	RiskScore   float64 `json:"risk_score"`
	Reputation  int    `json:"reputation"`
}

// Vessel represents an AIS vessel record
type Vessel struct {
	MMSI        string      `json:"mmsi"`
	IMO         string      `json:"imo,omitempty"`
	Name        string      `json:"name"`
	CurrentFlag string      `json:"current_flag"`
	Dimensions  Dimensions  `json:"dimensions"`
	FlagHistory []FlagEvent `json:"flag_history"`
}

// FlagEvent tracks a flag change event
type FlagEvent struct {
	Date       time.Time `json:"date"`
	Flag       string    `json:"flag"`
	PortOfCall string    `json:"port_of_call,omitempty"`
}

// Dimensions holds vessel measurements
type Dimensions struct {
	LengthMeters  float64 `json:"length_meters"`
	BeamMeters    float64 `json:"beam_meters"`
	DraftMeters   float64 `json:"draft_meters"`
	GrossTonnage  int     `json:"gross_tonnage"`
}

// AnomalyReport describes detected suspicious patterns
type AnomalyReport struct {
	VesselID    string      `json:"vessel_id"`
	Anomalies   []Anomaly   `json:"anomalies"`
	RiskScore   float64     `json:"risk_score"`
	Confidence  int         `json:"confidence"` // 1-5, higher is more certain
	Timestamp   time.Time   `json:"timestamp"`
}

// Anomaly describes a specific suspicious pattern
type Anomaly struct {
	Type        string    `json:"type"`
	Description string    `json:"description"`
	Severity    int       `json:"severity"` // 1-5, higher is worse
	Value       float64    `json:"value,omitempty"`
}

// Resolver handles vessel registry resolution and anomaly detection
type Resolver struct {
	registries     map[string]*Registry
	flagHistoryDB  map[string][]FlagEvent
	knownShells    []string
	mu             sync.RWMutex
	rng            *rand.Rand
}

// NewResolver creates a new resolver instance
func NewResolver() *Resolver {
	r := &Resolver{
		registries:     make(map[string]*Registry),
		flagHistoryDB:  make(map[string][]FlagEvent),
		knownShells:    []string{"PA", "LR", "LC", "GI", "KN", "VU", "SB"},
		rng:            rand.New(rand.NewSource(time.Now().UnixNano())),
	}

	// Initialize with sample registry data
	r.initializeRegistries()
	return r
}

func (r *Resolver) initializeRegistries() {
	registries := map[string]Registry{
		"US":  {"United States", "flag_state", 1.2, 95},
		"JP":  {"Japan", "flag_state", 0.8, 90},
		"GB":  {"United Kingdom", "flag_state", 1.0, 88},
		"DE":  {"Germany", "flag_state", 1.1, 87},
		"FR":  {"France", "flag_state", 1.0, 86},
		"NL":  {"Netherlands", "flag_state", 1.3, 85},
		"NO":  {"Norway", "flag_state", 1.4, 92},
		"PA":  {"Panama", "shell", 3.5, 60},
		"LR":  {"Liberia", "shell", 3.8, 55},
		"LC":  {"Saint Lucia", "shell", 4.2, 45},
		"GI":  {"Gibraltar", "shell", 3.0, 65},
		"KN":  {"Cayman Islands", "shell", 3.7, 58},
		"VU":  {"Vanuatu", "shell", 4.5, 42},
		"SB":  {"Samoa", "shell", 4.0, 48},
	}

	for code, reg := range registries {
		r.registries[code] = &reg
	}
}

// ResolveVessel attempts to resolve a vessel's identity and check for anomalies
func (r *Resolver) ResolveVessel(vessel Vessel) AnomalyReport {
	var anomalies []Anomaly
	totalScore := 0.0

	// Step 1: Check current flag against risk profile
	flagRisk, flagConfidence := r.checkCurrentFlag(vessel.CurrentFlag)
	if flagRisk > 0 {
		anomalies = append(anomalies, Anomaly{
			Type:        "HIGH_RISK_FLAG",
			Description: fmt.Sprintf("Vessel currently flagged under high-risk jurisdiction %s (risk score: %.1f)", vessel.CurrentFlag, flagRisk),
			Severity:    3,
			Value:       flagRisk,
		})
		totalScore += flagRisk * 2.0
	}

	// Step 2: Analyze flag history for rapid changes
	historyAnomalies := r.analyzeFlagHistory(vessel.FlagHistory)
	for _, a := range historyAnomalies {
		anomalies = append(anomalies, a)
		totalScore += a.Severity * 0.5
	}

	// Step 3: Check for IMO/Name mismatches (potential shell company activity)
	mismatchRisk, mismatchConfidence := r.checkIdentityConsistency(vessel)
	if mismatchRisk > 0 {
		anomalies = append(anomalies, Anomaly{
			Type:        "IDENTITY_MISMATCH",
			Description: fmt.Sprintf("Potential identity inconsistency detected (risk: %.1f)", mismatchRisk),
			Severity:    int(mismatchRisk * 2.5),
			Value:       mismatchRisk,
		})
		totalScore += mismatchRisk * 3.0
	}

	// Step 4: Check for rapid flag changes (classic evasion pattern)
	rapidChangeRisk := r.checkRapidFlagChanges(vessel.FlagHistory)
	if rapidChangeRisk > 0 {
		anomalies = append(anomalies, Anomaly{
			Type:        "RAPID_FLAG_CHANGE",
			Description: fmt.Sprintf("Multiple flag changes detected (risk score: %.1f)", rapidChangeRisk),
			Severity:    int(rapidChangeRisk * 2.0),
			Value:       rapidChangeRisk,
		})
		totalScore += rapidChangeRisk * 2.5
	}

	// Step 5: Check for shell registry usage
	shellUsage := r.checkShellRegistry(vessel.FlagHistory)
	if shellUsage > 0 {
		anomalies = append(anomalies, Anomaly{
			Type:        "SHELL_REGISTRY",
			Description: fmt.Sprintf("Vessel has used known shell registries (risk: %.1f)", shellUsage),
			Severity:    int(shellUsage * 2.5),
			Value:       shellUsage,
		})
		totalScore += shellUsage * 3.0
	}

	// Step 6: Check for name reuse across different MMSIs (ghost vessel pattern)
	nameReuseRisk := r.checkNameReuse(vessel.Name)
	if nameReuseRisk > 0 {
		anomalies = append(anomalies, Anomaly{
			Type:        "NAME_REUSE",
			Description: fmt.Sprintf("Vessel name may be reused/ghosted (risk: %.1f)", nameReuseRisk),
			Severity:    int(nameReuseRisk * 2.0),
			Value:       nameReuseRisk,
		})
		totalScore += nameReuseRisk * 2.0
	}

	// Calculate final confidence based on number of anomalies found
	confidence := min(5, len(anomalies)+1)

	return AnomalyReport{
		VesselID:    vessel.MMSI,
		Anomalies:   anomalies,
		RiskScore:   totalScore,
		Confidence:  confidence,
		Timestamp:   time.Now(),
	}
}

func (r *Resolver) checkCurrentFlag(flag string) (float64, int) {
	reg, exists := r.registries[strings.ToUpper(flag)]
	if !exists {
		return 1.5, 3 // Unknown flag treated as moderate risk
	}

	switch reg.Type {
	case "shell":
		return reg.RiskScore, 5
	case "flag_state", "port_state_control":
		baseRisk := 0.5 + (reg.RiskScore - 1.0) * 0.3
		if baseRisk < 0.2 {
			baseRisk = 0.2
		}
		return baseRisk, 4
	default:
		return reg.RiskScore, 4
	}
}

func (r *Resolver) analyzeFlagHistory(history []FlagEvent) []Anomaly {
	var anomalies []Anomaly

	if len(history) < 2 {
		return anomalies
	}

	// Sort by date
	sorted := make([]FlagEvent, len(history))
	copy(sorted, history)
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].Date.Before(sorted[j].Date)
	})

	// Check for rapid changes (more than 2 flags in 12 months)
	timeWindow := 365 * 24 * time.Hour
	rapidChanges := 0
	for i := 1; i < len(sorted); i++ {
		if sorted[i].Date.Sub(sorted[i-1].Date) > timeWindow/2 && 
		   (sorted[i].Flag != sorted[i-1].Flag || r.isShellRegistries(sorted[i].Flag)) {
			rapidChanges++
		}
	}

	if rapidChanges >= 2 {
		anomalies = append(anomalies, Anomaly{
			Type:        "RAPID_FLAG_HISTORY",
			Description: fmt.Sprintf("Multiple flag changes detected in short timeframe (changes: %d)", rapidChanges),
			Severity:    4,
			Value:       float64(rapidChanges) * 1.5,
		})
	}

	// Check for consecutive shell registry usage
	consecutiveShells := 0
	for i := 1; i < len(sorted); i++ {
		if r.isShellRegistries(sorted[i].Flag) && 
		   !r.isShellRegistries(sorted[i-1].Flag) {
			if consecutiveShells >= 2 {
				anomalies = append(anomalies, Anomaly{
					Type:        "CONSECUTIVE_SHELL_TRANSITION",
					Description: fmt.Sprintf("Transitioned from shell to another shell registry (current run: %d)", consecutiveShells),
					Severity:    3,
					Value:       float64(consecutiveShells) * 0.8,
				})
			}
			consecutiveShells = 1
		} else if r.isShellRegistries(sorted[i].Flag) {
			consecutiveShells++
		} else {
			consecutiveShells = 0
		}
	}

	return anomalies
}

func (r *Resolver) checkRapidFlagChanges(history []FlagEvent) float64 {
	if len(history) < 2 {
		return 0.0
	}

	sorted := make([]FlagEvent, len(history))
	copy(sorted, history)
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].Date.Before(sorted[j].Date)
	})

	minDaysBetween := 365 // Normal vessels change flags at least once a year
	maxChangesInWindow := 2

	var rapidScore float64 = 0.0
	
	for i := 1; i < len(sorted); i++ {
		daysDiff := int(sorted[i].Date.Sub(sorted[i-1].Date).Hours() / 24)
		
		if daysDiff < minDaysBetween && sorted[i].Flag != sorted[i-1].Flag {
			rapidScore += 0.5 // Each rapid change adds to risk
		}

		if i > maxChangesInWindow && 
		   (sorted[maxChangesInWindow+1-i].Date.Sub(sorted[0]).Hours() / 24) < 365*2 {
			// More than 2 changes in 2 years is suspicious
			rapidScore += 0.8
		}
	}

	return rapidScore
}

func (r *Resolver) checkShellRegistry(history []FlagEvent) float64 {
	score := 0.0
	
	for _, event := range history {
		if r.isShellRegistries(event.Flag) {
			reg, exists := r.registries[strings.ToUpper(event.Flag)]
			if exists && reg.Type == "shell" {
				score += (reg.RiskScore - 1.0) * 0.5
			} else if !exists {
				score += 0.3 // Unknown shell registry
			}
		}
	}

	return score
}

func (r *Resolver) isShellRegistries(flag string) bool {
	flag = strings.ToUpper(flag)
	for _, shell := range r.knownShells {
		if flag == shell || flag == "PA" && (flag == "LR" || flag == "LC") {
			return true
		}
	}
	return false
}

func (r *Resolver) checkIdentityConsistency(vessel Vessel) (float64, int) {
	score := 0.0
	
	// Check if IMO exists but doesn't match expected format for vessel size
	if vessel.IMO != "" && len(vessel.IMO) == 7 {
		// Valid IMO format check
		if !vessel.IMO[0:1].IsDigit() || 
		   !strings.HasPrefix(vessel.IMO, "9") && !strings.HasPrefix(vessel.IMO, "8") {
			score += 0.5 // Slightly unusual IMO prefix
		}
	}

	// Check for name variations that might indicate shell company activity
	nameVariations := map[string]bool{
		vessel.Name: true,
		strings.ToUpper(vessel.Name): true,
		strings.ToLower(vessel.Name): true,
	}

	if len(nameVariations) > 1 {
		score += 0.3 // Name has variations
	}

	return score, 4
}

func (r *Resolver) checkNameReuse(name string) float64 {
	// In a real system, this would query a database of known name reuses
	// For demo purposes, we simulate with some probability
	
	// Common names that might be reused
	commonNames := []string{
		"OCEAN STAR", "SEA PRINCESS", "ATLANTIC VOYAGER", 
		"PACIFIC DREAM", "NORTHERN LIGHTS", "EASTERN WIND"}

	for _, common := range commonNames {
		if strings.Contains(strings.ToUpper(name), strings.ToUpper(common)) {
			return 1.2 // High probability of name reuse
		}
	}

	return 0.3 // Low probability
}

// BatchResolve processes multiple vessels efficiently
func (r *Resolver) BatchResolve(vessels []Vessel) map[string]AnomalyReport {
	results := make(map[string]AnomalyReport, len(vessels))
	
	var wg sync.WaitGroup
	sem := make(chan struct{}, 10) // Limit concurrent operations

	for _, v := range vessels {
		wg.Add(1)
		sem <- struct{}{}
		
		go func(vs Vessel) {
			defer wg.Done()
			defer func() { <-sem }()
			
			results[vs.MMSI] = r.ResolveVessel(vs)
		}(v)
	}

	wg.Wait()
	return results
}

// GetRegistryInfo returns detailed info about a specific registry
func (r *Resolver) GetRegistryInfo(code string) (*Registry, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	
	reg, exists := r.registries[strings.ToUpper(code)]
	if !exists && len(registries) > 0 {
		// Try fuzzy matching
		for _, existing := range r.registries {
			if strings.Contains(strings