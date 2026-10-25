package main

import "testing"

type fake map[string]interface{}

func (f fake) Get(key string) interface{} { return f[key] }
func TestRecordedTeamCountersOnlyAndPostgame(t *testing.T) {
	r := fake{"m_iTeamNum": uint32(2), "m_iHeroKills": uint32(39), "m_iScore": uint32(0)}
	d := fake{"m_iTeamNum": uint32(3), "m_iHeroKills": uint32(24)}
	rules := fake{"m_pGameRules.m_nGameState": uint32(5)}
	if capture(rules, r, d, 1) != nil {
		t.Fatal("in-progress score must not be final")
	}
	rules["m_pGameRules.m_nGameState"] = uint32(6)
	s := capture(rules, r, d, 2)
	if s == nil || s.Fields["radiant_score"] != 39 || s.Fields["dire_score"] != 24 {
		t.Fatal("wrong authoritative counter")
	}
	r["m_iHeroKills"] = uint32(0)
	d["m_iHeroKills"] = uint32(0)
	if zero := capture(rules, r, d, 3); zero == nil || zero.Fields["radiant_score"] != 0 {
		t.Fatal("verified zero is valid")
	}
	delete(r, "m_iHeroKills")
	if capture(rules, r, d, 4) != nil {
		t.Fatal("must not fall back to base score or missing zero")
	}
}
func TestOldNewRuleAliasesAndClockNotEpoch(t *testing.T) {
	for _, prefix := range []string{"m_pGameRules.", ""} {
		rules := fake{prefix + "m_flGameStartTime": float32(100), prefix + "m_flGameEndTime": float32(1900), prefix + "m_lobbyType": uint32(0)}
		s := &snapshot{Fields: map[string]interface{}{}, Provenance: map[string]string{}}
		enrichRules(s, rules)
		if s.Fields["duration"] != float64(1800) || s.Fields["lobby_type"] != 0 {
			t.Fatal("clock/lobby alias failed")
		}
		if _, exists := s.Fields["start_time"]; exists {
			t.Fatal("relative clock is not an epoch date")
		}
		rules[prefix+"m_flGameEndTime"] = float32(2000)
		enrichRules(s, rules)
		if s.Fields["duration"] != float64(1800) {
			t.Fatal("final clock changed after freezing")
		}
	}
}

func TestAbsentLobbySentinelDoesNotBecomeKnown(t *testing.T) {
	s := &snapshot{Fields: map[string]interface{}{}, Provenance: map[string]string{}}
	enrichRules(s, fake{"m_pGameRules.m_lobbyType": int32(-1)})
	if _, exists := s.Fields["lobby_type"]; exists {
		t.Fatal("negative missing-value sentinel must stay unknown")
	}
}
