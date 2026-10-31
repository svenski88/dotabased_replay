package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"
)

func TestPhysicalBuildingsRequireKnownCompleteSetsAndCountDenies(t *testing.T) {
	g := newGraphState()
	if r, _, _, _ := g.buildingTotals(); r != nil {
		t.Fatal("missing structures cannot be zero")
	}
	for team := 2; team <= 3; team++ {
		for i := 0; i < 11; i++ {
			g.buildings[fmt.Sprintf("tower:%d:%d", team, i)] = &graphBuilding{kind: "tower", team: team, known: true, dead: i < 2}
		}
		for i := 0; i < 6; i++ {
			g.buildings[fmt.Sprintf("rax:%d:%d", team, i)] = &graphBuilding{kind: "barracks", team: team, known: true, dead: i < 1}
		}
	}
	r, d, rr, rd := g.buildingTotals()
	if r == nil || d == nil || rr == nil || rd == nil || *r != 2 || *d != 2 || *rr != 1 || *rd != 1 {
		t.Fatal("wrong physical losses")
	}
	// Attacker identity is irrelevant to a physical building's dead state (denies).
	g.buildings["tower:2:10"].dead = true
	r, _, _, _ = g.buildingTotals()
	if *r != 3 {
		t.Fatal("denied tower omitted")
	}
	if buildingKind("CDOTA_BaseNPC_Watch_Tower") != "" {
		t.Fatal("outpost counted as tower")
	}
}

func TestTwinTierFourEntitiesKeepDistinctMarkersAndCombatNames(t *testing.T) {
	g := newGraphState()
	start, at, team := 100.0, 200.0, 2.0
	g.start = &start
	g.Events = []graphEvent{
		{Kind: "tower", Entity: "1:1", TargetTeam: &team, absTime: &at, Source: "building_entity"},
		{Kind: "tower", Entity: "2:1", TargetTeam: &team, absTime: &at, Source: "building_entity"},
	}
	g.addDeath("npc_dota_goodguys_tower4", "npc_dota_hero_lina", false, false, &at, 600, nil, nil, "test")
	g.addDeath("npc_dota_goodguys_tower4", "npc_dota_hero_lina", false, false, &at, 601, nil, nil, "test")
	events := g.normalizedEvents()
	if len(events) != 2 || events[0].Entity == events[1].Entity {
		t.Fatal("distinct towers merged or duplicated", events)
	}
	if events[0].Target != "npc_dota_goodguys_tower4" || events[0].Attacker != "npc_dota_hero_lina" {
		t.Fatal("combat detail lost")
	}
	if events[0].Time == nil || *events[0].Time != 100 {
		t.Fatal("wrong clock")
	}
}

func TestPlayerSlotsRemainStableAcrossSparsePlayerIDs(t *testing.T) {
	g := newGraphState()
	players := fake{}
	r, d := fake{}, fake{}
	for slot := 0; slot < 5; slot++ {
		for team := 2; team <= 3; team++ {
			player := slot*3 + (team-2)*20
			players[fmt.Sprintf("m_vecPlayerData.%04d.m_iPlayerTeam", player)] = uint32(team)
			players[fmt.Sprintf("m_vecPlayerTeamData.%04d.m_iTeamSlot", player)] = uint32(slot)
		}
		r[fmt.Sprintf("m_vecDataTeam.%04d.m_iNetWorth", slot)] = uint32(100 + slot)
		d[fmt.Sprintf("m_vecDataTeam.%04d.m_iNetWorth", slot)] = uint32(200 + slot)
	}
	g.players = players
	g.data[2] = r
	g.data[3] = d
	values := g.playerNetWorth()
	if len(values) != 10 || *values[0] != 100 || *values[4] != 104 || *values[5] != 200 || *values[9] != 204 {
		t.Fatal(values)
	}
}

func TestGraphStreamEmptyIsUnavailableAndEachRecordBounded(t *testing.T) {
	g := newGraphState()
	result := map[string]interface{}{}
	var out bytes.Buffer
	if err := g.emit(json.NewEncoder(&out), result); err != nil {
		t.Fatal(err)
	}
	if result["graph_complete"] != false || result["graph_sample_count"] != 0 {
		t.Fatal(result)
	}
	for i := 0; i < 1000; i++ {
		g.Samples = append(g.Samples, graphSample{Time: i, PlayerNW: make([]*float64, 10)})
	}
	if err := g.emit(json.NewEncoder(&out), result); err != nil {
		t.Fatal(err)
	}
	if out.Len() < 131072 {
		t.Fatal("fixture must exceed old whole-result cap")
	}
	for _, line := range bytes.Split(out.Bytes(), []byte("\n")) {
		if len(line) > 131072 {
			t.Fatal("unbounded record")
		}
	}
}
