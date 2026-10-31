package main

import (
	"fmt"
	"math"
	"testing"
)

func TestGraphSamplesPreserveReplayTicksAcrossPauses(t *testing.T) {
	g := newGraphState()
	rules := fake{"m_pGameRules.m_flGameStartTime": float32(100), "m_pGameRules.m_fGameTime": float32(200), "m_pGameRules.m_nGameState": uint32(5)}
	g.rules = rules
	g.replayTick = 12345
	g.sample()
	g.replayTick = 20000
	g.sample() // pause: same game time, advancing replay tick
	if len(g.Samples) != 1 || g.Samples[0].ReplayTick != 12345 {
		t.Fatal("first sample must retain its recorded replay tick")
	}
	rules["m_pGameRules.m_fGameTime"] = float32(201)
	g.replayTick = 20030
	g.sample()
	if len(g.Samples) != 2 || g.Samples[1].Time != 101 || g.Samples[1].ReplayTick != 20030 {
		t.Fatal("resumed clock must not infer ticks from game seconds")
	}
}

func TestGraphSecondDoesNotFillGapsOrAdvanceDuringPause(t *testing.T) {
	last := -1
	for _, at := range []float64{-4, 0.1, 0.2, 0.9, 1.1, 1.1, 4.2} {
		next, ok := graphSecond(at, last)
		if ok {
			last = next
		}
	}
	if last != 4 {
		t.Fatal(last)
	}
	if _, ok := graphSecond(4.9, last); ok {
		t.Fatal("duplicate second")
	}
	if _, ok := graphSecond(math.NaN(), last); ok {
		t.Fatal("NaN clock")
	}
}

func TestGraphClockUsesRecordedIntervalAndPausedTicks(t *testing.T) {
	rules := fake{"m_pGameRules.m_nTotalPausedTicks": uint32(300), "m_pGameRules.m_bGamePaused": false, "m_pGameRules.m_nPauseStartTick": uint32(600)}
	if now, ok := graphClock(rules, 900, 1.0/30); !ok || now != 20 {
		t.Fatalf("clock %v %v", now, ok)
	}
	rules["m_pGameRules.m_bGamePaused"] = true
	if now, ok := graphClock(rules, 1200, 1.0/30); !ok || now != 10 {
		t.Fatalf("pause clock %v %v", now, ok)
	}
	if _, ok := graphClock(rules, 1200, 0); ok {
		t.Fatal("must not assume tick rate")
	}
	delete(rules, "m_pGameRules.m_nTotalPausedTicks")
	if _, ok := graphClock(rules, 1200, 1.0/30); ok {
		t.Fatal("missing paused ticks")
	}
	rules["m_pGameRules.m_fGameTime"] = float32(123)
	if now, ok := graphClock(rules, 0, 0); !ok || now != 123 {
		t.Fatal("legacy recorded clock")
	}
}

func graphFixture() (*graphState, fake, fake) {
	g := newGraphState()
	players := fake{}
	data := fake{}
	for i := 0; i < 5; i++ {
		players[fmt.Sprintf("m_vecPlayerData.%04d.m_iPlayerTeam", i)] = uint32(2)
		players[fmt.Sprintf("m_vecPlayerTeamData.%04d.m_iTeamSlot", i)] = uint32(i)
		data[fmt.Sprintf("m_vecDataTeam.%04d.m_iNetWorth", i)] = uint32(1000)
		data[fmt.Sprintf("m_vecDataTeam.%04d.m_iTotalEarnedXP", i)] = uint32(0)
	}
	g.players = players
	g.data[2] = data
	return g, players, data
}

func TestGraphTotalsRequireFiveDistinctKnownPlayers(t *testing.T) {
	g, players, data := graphFixture()
	n, x := g.totals(2)
	if n == nil || *n != 5000 || x == nil || *x != 0 {
		t.Fatal("valid totals and recorded zero")
	}
	delete(data, "m_vecDataTeam.0001.m_iNetWorth")
	n, x = g.totals(2)
	if n != nil || x == nil {
		t.Fatal("missing NW should not erase known XP or become zero")
	}
	players["m_vecPlayerTeamData.0004.m_iTeamSlot"] = uint32(0)
	if n, x := g.totals(2); n != nil || x != nil {
		t.Fatal("duplicate team slots")
	}
	if graphDifference(nil, x) != nil {
		t.Fatal("missing difference")
	}
}

func TestGraphDeathsFilterIllusionsAndDeduplicate(t *testing.T) {
	g := newGraphState()
	at := 123.0
	g.addDeath("npc_dota_hero_axe", "npc_dota_hero_lina", true, true, &at, 10, nil, nil, "test")
	g.addDeath("npc_dota_creep_badguys_melee", "npc_dota_hero_lina", false, false, &at, 10, nil, nil, "test")
	if len(g.Events) != 0 {
		t.Fatal("illusion/creep counted")
	}
	for _, tick := range []uint32{10, 15} {
		g.addDeath("npc_dota_hero_axe", "npc_dota_hero_lina", true, false, &at, tick, nil, nil, "test")
	}
	if len(g.Events) != 1 {
		t.Fatal("bulk retransmission duplicated")
	}
	at = 124
	g.addDeath("npc_dota_hero_axe", "npc_dota_hero_lina", true, false, &at, 30, nil, nil, "test")
	if len(g.Events) != 2 {
		t.Fatal("distinct death removed")
	}
	for target, kind := range map[string]string{"npc_dota_roshan": "roshan", "npc_dota_badguys_tower1_mid": "tower", "npc_dota_goodguys_melee_rax_bot": "barracks"} {
		if graphKind(target, false, false) != kind {
			t.Fatal(target)
		}
	}
}

func TestGraphIncompleteProbeStillHasStructuredResult(t *testing.T) {
	result := graphProbe(t.TempDir() + "/absent.dem")
	if result["complete"] != false || result["error"] == nil || result["samples"] == nil || result["events"] == nil {
		t.Fatal(result)
	}
}
