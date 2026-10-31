package main

import (
	"encoding/json"
	"fmt"
	"github.com/dotabuff/manta"
	"math"
	"strings"
)

type graphBuilding struct {
	kind  string
	team  int
	dead  bool
	known bool
}

func buildingKind(class string) string {
	switch strings.TrimPrefix(class, "C_") {
	case "CDOTA_BaseNPC_Tower", "DOTA_BaseNPC_Tower":
		return "tower"
	case "CDOTA_BaseNPC_Barracks", "DOTA_BaseNPC_Barracks":
		return "barracks"
	}
	return ""
}

func (g *graphState) observeBuilding(e *manta.Entity, op manta.EntityOp, tick uint32) {
	kind := buildingKind(e.GetClassName())
	if kind == "" {
		return
	}
	id := fmt.Sprintf("%d:%d", e.GetIndex(), e.GetSerial())
	if op.Flag(manta.EntityOpDeleted) {
		return
	} // disappearance alone is not a recorded death
	team := graphNumber(e, "m_iTeamNum")
	if team == nil || (*team != 2 && *team != 3) {
		return
	}
	health, hok := number(e, "m_iHealth")
	life, lok := number(e, "m_lifeState")
	if !hok && !lok {
		return
	}
	dead := (hok && health <= 0) || (lok && life != 0)
	previous, existed := g.buildings[id]
	g.buildings[id] = &graphBuilding{kind: kind, team: int(*team), dead: dead, known: true}
	if dead && existed && !previous.dead {
		var at *float64
		if now, ok := graphClock(g.rules, g.netTick, g.tickInterval); ok {
			at = &now
		}
		target := fmt.Sprintf("%s_team_%d", kind, int(*team))
		g.Events = append(g.Events, graphEvent{Kind: kind, Tick: tick, Target: target, TargetTeam: team, Source: "building_entity", Entity: id, absTime: at})
	}
}

func (g *graphState) buildingTotals() (*float64, *float64, *float64, *float64) {
	totals := func(kind string, team, expected int) *float64 {
		count, dead := 0, 0
		for _, b := range g.buildings {
			if b.kind == kind && b.team == team && b.known {
				count++
				if b.dead {
					dead++
				}
			}
		}
		if count != expected {
			return nil
		}
		v := float64(dead)
		return &v
	}
	return totals("tower", 2, 11), totals("tower", 3, 11), totals("barracks", 2, 6), totals("barracks", 3, 6)
}

func (g *graphState) playerNetWorth() []*float64 {
	out := make([]*float64, 10)
	seen := map[int]bool{}
	if g.players == nil {
		return out
	}
	for player := 0; player < 64; player++ {
		prefix := fmt.Sprintf("m_vecPlayerData.%04d.", player)
		team := graphNumber(g.players, prefix+"m_iPlayerTeam", fmt.Sprintf("m_iPlayerTeams.%04d", player))
		slot := graphNumber(g.players, fmt.Sprintf("m_vecPlayerTeamData.%04d.m_iTeamSlot", player), prefix+"m_iTeamSlot", fmt.Sprintf("m_iTeamSlot.%04d", player))
		if team == nil || slot == nil || (*team != 2 && *team != 3) || *slot >= 5 {
			continue
		}
		index := int(*slot)
		if *team == 3 {
			index += 5
		}
		if seen[index] {
			return make([]*float64, 10)
		}
		seen[index] = true
		out[index] = graphNumber(g.data[int(*team)], fmt.Sprintf("m_vecDataTeam.%04d.m_iNetWorth", int(*slot)))
		if out[index] == nil {
			out[index] = graphNumber(g.players, fmt.Sprintf("m_vecPlayerTeamData.%04d.m_iNetWorth", player), fmt.Sprintf("m_iNetWorth.%04d", player))
		}
	}
	return out
}

func (g *graphState) normalizedEvents() []graphEvent {
	events := append([]graphEvent{}, g.Events...)
	// Pair named combat entries with physical identities. Two tier-four entities
	// may share a combat-log name and timestamp: neither physical death is merged.
	used := map[int]bool{}
	for i := range events {
		e := &events[i]
		if e.Kind != "tower" && e.Kind != "barracks" {
			continue
		}
		best := -1
		distance := 2.01
		for j, log := range g.objectiveLog {
			if used[j] || log.Kind != e.Kind || e.TargetTeam == nil || log.TargetTeam == nil || *e.TargetTeam != *log.TargetTeam || e.absTime == nil || log.absTime == nil {
				continue
			}
			delta := math.Abs(*e.absTime - *log.absTime)
			if delta < distance {
				best = j
				distance = delta
			}
		}
		if best >= 0 {
			log := g.objectiveLog[best]
			e.Target = log.Target
			e.Attacker = log.Attacker
			e.AttackerTeam = log.AttackerTeam
			e.Source = "building_entity+" + log.Source
			used[best] = true
		}
	}
	for i, log := range g.objectiveLog {
		if !used[i] {
			events = append(events, log)
		}
	}
	for i := range events {
		e := &events[i]
		if e.absTime != nil && g.start != nil {
			v := *e.absTime - *g.start
			e.Time = &v
		}
		if e.AttackerTeam == nil {
			if t, ok := g.heroTeams[e.Attacker]; ok {
				v := float64(t)
				e.AttackerTeam = &v
			}
		}
		if e.TargetTeam == nil {
			if t, ok := g.heroTeams[e.Target]; ok {
				v := float64(t)
				e.TargetTeam = &v
			}
		}
	}
	return events
}

// Keep the app's framing limit: each graph record is small, never one giant result.
func (g *graphState) emit(encoder *json.Encoder, result map[string]interface{}) error {
	for _, sample := range g.Samples {
		if err := encoder.Encode(map[string]interface{}{"event": "graph_sample", "entry": sample}); err != nil {
			return err
		}
	}
	events := g.normalizedEvents()
	for _, event := range events {
		if err := encoder.Encode(map[string]interface{}{"event": "graph_event", "entry": event}); err != nil {
			return err
		}
	}
	result["graph_schema_version"] = 1
	result["graph_complete"] = len(g.Samples) > 0 && g.start != nil && g.end != nil && g.final != nil
	result["graph_sample_count"] = len(g.Samples)
	result["graph_event_count"] = len(events)
	result["graph_clock_source"] = g.clockSource
	return nil
}
