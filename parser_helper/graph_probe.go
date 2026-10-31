// Shared timeline extraction and opt-in development diagnostics.
package main

import (
	"fmt"
	"math"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
)

type graphSample struct {
	Time         int        `json:"time"`
	ReplayTick   uint32     `json:"replay_tick"`
	ObservedTime float64    `json:"observed_time"`
	RadiantNW    *float64   `json:"radiant_net_worth"`
	DireNW       *float64   `json:"dire_net_worth"`
	NWDifference *float64   `json:"net_worth_difference"`
	RadiantXP    *float64   `json:"radiant_xp"`
	DireXP       *float64   `json:"dire_xp"`
	XPDifference *float64   `json:"xp_difference"`
	RadiantScore *float64   `json:"radiant_score"`
	DireScore    *float64   `json:"dire_score"`
	PlayerNW     []*float64 `json:"player_net_worth"`
	TowersR      *float64   `json:"towers_dead_R"`
	TowersD      *float64   `json:"towers_dead_D"`
	RaxR         *float64   `json:"rax_dead_R"`
	RaxD         *float64   `json:"rax_dead_D"`
}

type graphEvent struct {
	Kind         string   `json:"kind"`
	Time         *float64 `json:"time"`
	Tick         uint32   `json:"tick"`
	Attacker     string   `json:"attacker"`
	Target       string   `json:"target"`
	AttackerTeam *float64 `json:"attacker_team"`
	TargetTeam   *float64 `json:"target_team"`
	Source       string   `json:"source"`
	Entity       string   `json:"entity,omitempty"`
	absTime      *float64
}

type graphState struct {
	rules        getter
	players      getter
	data         map[int]getter
	teams        map[int]getter
	fields       map[string]map[string]bool
	diagnostics  bool
	lastSecond   int
	Samples      []graphSample
	objectiveLog []graphEvent
	Events       []graphEvent
	seen         map[string]bool
	combatCount  int
	unresolved   int
	start        *float64
	end          *float64
	final        *snapshot
	heroTeams    map[string]int
	netTick      uint32
	replayTick   uint32
	tickInterval float64
	clockSource  string
	winner       int
	buildings    map[string]*graphBuilding
}

func newGraphState() *graphState {
	return &graphState{data: map[int]getter{}, teams: map[int]getter{}, fields: map[string]map[string]bool{}, heroTeams: map[string]int{}, buildings: map[string]*graphBuilding{}, lastSecond: -1, Samples: []graphSample{}, Events: []graphEvent{}, seen: map[string]bool{}}
}

func graphNumber(e getter, names ...string) *float64 {
	if e == nil {
		return nil
	}
	v, ok := number(e, names...)
	if !ok || v < 0 {
		return nil
	}
	return &v
}

func graphDifference(r, d *float64) *float64 {
	if r == nil || d == nil {
		return nil
	}
	v := *r - *d
	return &v
}

// Never manufacture samples for skipped seconds or advance time during pauses.
func graphSecond(now float64, last int) (int, bool) {
	if math.IsNaN(now) || math.IsInf(now, 0) || now < 0 {
		return last, false
	}
	s := int(math.Floor(now))
	return s, s > last
}

func (g *graphState) totals(team int) (*float64, *float64) {
	if g.players == nil {
		return nil, nil
	}
	nw, xp, count, nwCount, xpCount := 0.0, 0.0, 0, 0, 0
	slots := map[int]bool{}
	for player := 0; player < 64; player++ {
		prefix := fmt.Sprintf("m_vecPlayerData.%04d.", player)
		t := graphNumber(g.players, prefix+"m_iPlayerTeam", fmt.Sprintf("m_iPlayerTeams.%04d", player))
		if t == nil || int(*t) != team {
			continue
		}
		// Team membership alone can include coaches; require a playing team slot.
		slot := graphNumber(g.players, fmt.Sprintf("m_vecPlayerTeamData.%04d.m_iTeamSlot", player), prefix+"m_iTeamSlot", fmt.Sprintf("m_iTeamSlot.%04d", player))
		if slot == nil || *slot >= 5 {
			continue
		}
		if slots[int(*slot)] {
			return nil, nil
		}
		slots[int(*slot)] = true
		count++
		teamPrefix := fmt.Sprintf("m_vecDataTeam.%04d.", int(*slot))
		n := graphNumber(g.data[team], teamPrefix+"m_iNetWorth")
		if n == nil {
			n = graphNumber(g.players, fmt.Sprintf("m_vecPlayerTeamData.%04d.m_iNetWorth", player), fmt.Sprintf("m_iNetWorth.%04d", player))
		}
		x := graphNumber(g.players, fmt.Sprintf("m_vecPlayerTeamData.%04d.m_iTotalEarnedXP", player), fmt.Sprintf("m_iTotalEarnedXP.%04d", player))
		if x == nil {
			x = graphNumber(g.data[team], teamPrefix+"m_iTotalEarnedXP")
		}
		if n != nil {
			nw += *n
			nwCount++
		}
		if x != nil {
			xp += *x
			xpCount++
		}
	}
	var n, x *float64
	if count == 5 && nwCount == 5 {
		n = &nw
	}
	if count == 5 && xpCount == 5 {
		x = &xp
	}
	return n, x
}

// Modern replays removed m_fGameTime. Recorded server interval and paused ticks
// reconstruct the same pause-aware engine clock; no wall time or assumed 30 Hz.
func graphClock(rules getter, netTick uint32, interval float64) (float64, bool) {
	if rules == nil {
		return 0, false
	}
	if now, ok := rule(rules, "m_fGameTime"); ok {
		return now, true
	}
	if interval <= 0 || math.IsNaN(interval) || math.IsInf(interval, 0) {
		return 0, false
	}
	pausedTicks, ok := rule(rules, "m_nTotalPausedTicks")
	if !ok {
		return 0, false
	}
	var paused bool
	switch p := rules.Get("m_pGameRules.m_bGamePaused").(type) {
	case bool:
		paused = p
	default:
		switch p := rules.Get("m_bGamePaused").(type) {
		case bool:
			paused = p
		default:
			return 0, false
		}
	}
	tick := float64(netTick)
	if paused {
		var ok bool
		tick, ok = rule(rules, "m_nPauseStartTick")
		if !ok {
			return 0, false
		}
	}
	if tick < pausedTicks {
		return 0, false
	}
	return (tick - pausedTicks) * interval, true
}

func (g *graphState) sample() {
	if g.rules == nil {
		return
	}
	start, sok := rule(g.rules, "m_flGameStartTime")
	if g.final == nil {
		g.final = capture(g.rules, g.teams[2], g.teams[3], 0)
	}
	now, nok := graphClock(g.rules, g.netTick, g.tickInterval)
	state, stok := rule(g.rules, "m_nGameState")
	if !sok || start <= 0 || !nok || !stok || state < 5 {
		return
	}
	g.start = &start
	if _, ok := rule(g.rules, "m_fGameTime"); ok {
		g.clockSource = "m_fGameTime"
	} else {
		g.clockSource = "(server tick - total paused ticks) * recorded server tick_interval; pause start tick while paused"
	}
	if end, ok := rule(g.rules, "m_flGameEndTime"); ok && end > 0 {
		g.end = &end
	}
	if state > 5 && len(g.Samples) > 0 {
		return
	}
	sec, ok := graphSecond(now-start, g.lastSecond)
	if !ok {
		return
	}
	g.lastSecond = sec
	rn, rx := g.totals(2)
	dn, dx := g.totals(3)
	tr, td, rr, rd := g.buildingTotals()
	g.Samples = append(g.Samples, graphSample{ReplayTick: g.replayTick, PlayerNW: g.playerNetWorth(), TowersR: tr, TowersD: td, RaxR: rr, RaxD: rd, Time: sec, ObservedTime: now - start, RadiantNW: rn, DireNW: dn, NWDifference: graphDifference(rn, dn), RadiantXP: rx, DireXP: dx, XPDifference: graphDifference(rx, dx), RadiantScore: graphNumber(g.teams[2], "m_iHeroKills"), DireScore: graphNumber(g.teams[3], "m_iHeroKills")})
}

func graphKind(target string, hero, illusion bool) string {
	if illusion {
		return ""
	}
	if hero && strings.HasPrefix(target, "npc_dota_hero_") {
		return "hero_death"
	}
	if target == "npc_dota_roshan" {
		return "roshan"
	}
	if strings.Contains(target, "_tower") {
		return "tower"
	}
	if strings.Contains(target, "_rax_") || strings.Contains(target, "_barracks") {
		return "barracks"
	}
	return ""
}

func (g *graphState) addDeath(target, attacker string, hero, illusion bool, at *float64, tick uint32, attackerTeam, targetTeam *float64, source string) {
	kind := graphKind(target, hero, illusion)
	if kind == "" {
		return
	}
	// Combat-log bulk retransmissions can repeat the same absolute event.
	stamp := fmt.Sprint(tick)
	if at != nil {
		stamp = fmt.Sprintf("%.4f", *at)
	}
	key := kind + ":" + target + ":" + attacker + ":" + stamp
	if g.seen[key] {
		return
	}
	g.seen[key] = true
	event := graphEvent{Kind: kind, Tick: tick, Target: target, Attacker: attacker, AttackerTeam: attackerTeam, TargetTeam: targetTeam, Source: source, absTime: at}
	if kind == "tower" || kind == "barracks" {
		if event.TargetTeam == nil {
			if strings.Contains(target, "goodguys") {
				v := float64(2)
				event.TargetTeam = &v
			}
			if strings.Contains(target, "badguys") {
				v := float64(3)
				event.TargetTeam = &v
			}
		}
		g.objectiveLog = append(g.objectiveLog, event)
	} else {
		g.Events = append(g.Events, event)
	}
}

func (g *graphState) discover(e *manta.Entity) {
	class := e.GetClassName()
	if g.fields[class] == nil {
		g.fields[class] = map[string]bool{}
	}
	for key := range e.Map() {
		low := strings.ToLower(key)
		for _, term := range []string{"networth", "earnedxp", "team", "playerid", "gametime", "starttime", "endtime", "gamestate", "herokills", "winprob", "win_prob", "winchance", "win_chance"} {
			if strings.Contains(low, term) {
				g.fields[class][key] = true
				break
			}
		}
	}
}

func graphProbe(path string) (result map[string]interface{}) {
	begin := time.Now()
	g := newGraphState()
	g.diagnostics = true // Property discovery is only needed by the explicit probe.
	result = map[string]interface{}{"probe_version": 1, "complete": false, "samples": g.Samples, "events": g.Events, "engine_build": 0}
	defer func() {
		if recovered := recover(); recovered != nil {
			result["error"] = fmt.Sprint(recovered)
			result["complete"] = false
		}
		if g.start != nil {
			result["game_start"] = *g.start
		}
		if g.end != nil {
			result["game_end"] = *g.end
		}
		g.Events = g.normalizedEvents()
		result["samples"] = g.Samples
		result["events"] = g.Events
		fields := map[string][]string{}
		candidates := []string{}
		for class, keys := range g.fields {
			for k := range keys {
				fields[class] = append(fields[class], k)
				low := strings.ToLower(k)
				if strings.Contains(low, "winprob") || strings.Contains(low, "win_prob") || strings.Contains(low, "winchance") || strings.Contains(low, "win_chance") {
					candidates = append(candidates, class+"."+k)
				}
			}
			sort.Strings(fields[class])
		}
		sort.Strings(candidates)
		result["diagnostics"] = map[string]interface{}{"fields": fields, "clock_source": g.clockSource, "tick_interval": g.tickInterval, "team_attribution_note": "Combat-log team fields where recorded; otherwise recorded summary hero/team mapping, with unknown retained for unresolved units.", "win_probability_candidates": candidates, "combat_log_count": g.combatCount, "unresolved_deaths": g.unresolved, "win_probability_note": "Pinned protobuf defines CDOTAMatchPrivateMetadata.graph_win_probability; no assumption that separate private match metadata is embedded in replay."}
		result["final_score"] = map[string]interface{}{"radiant": nil, "dire": nil}
		if g.winner != 0 {
			result["winner"] = g.winner
		}
		if g.final != nil {
			result["final_score"] = map[string]interface{}{"radiant": g.final.Fields["radiant_score"], "dire": g.final.Fields["dire_score"]}
		}
		result["elapsed_seconds"] = time.Since(begin).Seconds()
	}()
	f, err := os.Open(path)
	if err != nil {
		result["error"] = err.Error()
		return
	}
	defer f.Close()
	p, err := manta.NewStreamParser(f)
	if err != nil {
		result["error"] = err.Error()
		return
	}
	attachGraph(p, g)
	err = p.Start()
	result["engine_build"] = p.GameBuild
	if err != nil {
		result["error"] = err.Error()
		return
	}
	if g.final == nil {
		result["error"] = "No authoritative post-game score snapshot"
		return
	}
	result["complete"] = true
	return
}

func attachGraph(p *manta.Parser, g *graphState) {
	p.Callbacks.OnCSVCMsg_ServerInfo(func(m *dota.CSVCMsg_ServerInfo) error {
		if m.TickInterval != nil {
			g.tickInterval = float64(m.GetTickInterval())
		}
		return nil
	})
	p.Callbacks.OnCNETMsg_Tick(func(m *dota.CNETMsg_Tick) error { g.netTick = m.GetTick(); return nil })
	lookup := func(index uint32) string { s, _ := p.LookupStringByIndex("CombatLogNames", int32(index)); return s }
	combat := func(m *dota.CMsgDOTACombatLogEntry) error {
		g.combatCount++
		if m.GetType() != dota.DOTA_COMBATLOG_TYPES_DOTA_COMBATLOG_DEATH {
			return nil
		}
		target := lookup(m.GetTargetName())
		if target == "" {
			g.unresolved++
			return nil
		}
		var at, a, t *float64
		if m.Timestamp != nil {
			v := float64(m.GetTimestamp())
			at = &v
		}
		if m.AttackerTeam != nil {
			v := float64(m.GetAttackerTeam())
			a = &v
		}
		if m.TargetTeam != nil {
			v := float64(m.GetTargetTeam())
			t = &v
		}
		g.addDeath(target, lookup(m.GetAttackerName()), m.GetIsTargetHero(), m.GetIsTargetIllusion(), at, p.Tick, a, t, "CMsgDOTACombatLogEntry")
		return nil
	}
	p.Callbacks.OnCMsgDOTACombatLogEntry(combat)
	p.Callbacks.OnCDOTAUserMsg_CombatLogBulkData(func(m *dota.CDOTAUserMsg_CombatLogBulkData) error {
		for _, entry := range m.GetCombatEntries() {
			combat(entry)
		}
		return nil
	})
	p.OnGameEvent("dota_combatlog", func(m *manta.GameEvent) error {
		g.combatCount++
		if m.Type() != dota.DOTA_COMBATLOG_TYPES_DOTA_COMBATLOG_DEATH {
			return nil
		}
		i, err := m.GetInt32("targetname")
		if err != nil {
			g.unresolved++
			return nil
		}
		a, _ := m.GetInt32("attackername")
		hero, _ := m.GetBool("targethero")
		illusion, _ := m.GetBool("targetillusion")
		var at *float64
		if v, err := m.GetFloat32("timestamp"); err == nil {
			n := float64(v)
			at = &n
		}
		g.addDeath(lookup(uint32(i)), lookup(uint32(a)), hero, illusion, at, p.Tick, nil, nil, "dota_combatlog")
		return nil
	})
	p.Callbacks.OnCDemoFileInfo(func(info *dota.CDemoFileInfo) error {
		if game := info.GetGameInfo().GetDota(); game != nil {
			if w := game.GetGameWinner(); w == 2 || w == 3 {
				g.winner = int(w)
			}
			for _, player := range game.GetPlayerInfo() {
				if team := player.GetGameTeam(); team == 2 || team == 3 {
					g.heroTeams[player.GetHeroName()] = int(team)
				}
			}
		}
		return nil
	})
	p.OnEntity(func(e *manta.Entity, op manta.EntityOp) error {
		g.replayTick = p.Tick
		g.observeBuilding(e, op, p.Tick)
		if op.Flag(manta.EntityOpDeleted) {
			return nil
		}
		class := e.GetClassName()
		low := strings.ToLower(class)
		isRules := strings.Contains(low, "gamerules")
		interesting := isRules || strings.Contains(low, "playerresource") || strings.Contains(low, "dataradiant") || strings.Contains(low, "datadire") || class == "CDOTATeam" || class == "C_DOTATeam"
		if !interesting {
			return nil
		}
		if isRules {
			g.rules = e
		}
		if strings.Contains(low, "playerresource") {
			g.players = e
		}
		if strings.Contains(low, "dataradiant") {
			g.data[2] = e
		}
		if strings.Contains(low, "datadire") {
			g.data[3] = e
		}
		if class == "CDOTATeam" || class == "C_DOTATeam" {
			if t := graphNumber(e, "m_iTeamNum"); t != nil {
				g.teams[int(*t)] = e
			}
		}
		// Enumerating entity properties is expensive and serves only the probe.
		// Runtime extraction reads known fields directly and never needs this map.
		if g.diagnostics && (g.fields[class] == nil || isRules) {
			g.discover(e)
		}
		g.sample()
		return nil
	})
}
