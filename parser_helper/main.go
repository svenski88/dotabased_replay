// Local replay metadata helper. Replay inputs never leave this process/machine.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"io"
	"math"
	"os"
	"strings"
	"time"
)

const Version = "1.2.1+manta1.5.2"

type getter interface{ Get(string) interface{} }

func number(e getter, names ...string) (float64, bool) {
	for _, name := range names {
		var value float64
		switch v := e.Get(name).(type) {
		case uint32:
			value = float64(v)
		case uint64:
			value = float64(v)
		case int32:
			value = float64(v)
		case int64:
			value = float64(v)
		case int:
			value = float64(v)
		case float32:
			value = float64(v)
		case float64:
			value = v
		default:
			continue
		}
		if !math.IsNaN(value) && !math.IsInf(value, 0) {
			return value, true
		}
	}
	return 0, false
}
func rule(e getter, field string) (float64, bool) { return number(e, "m_pGameRules."+field, field) }

type snapshot struct {
	Fields     map[string]interface{} `json:"fields"`
	Provenance map[string]string      `json:"provenance"`
	Tick       uint32                 `json:"final_tick"`
	State      int                    `json:"final_state"`
}

func capture(rules getter, radiant getter, dire getter, tick uint32) *snapshot {
	if rules == nil || radiant == nil || dire == nil {
		return nil
	}
	state, ok := rule(rules, "m_nGameState")
	if !ok || (state != 6 && state != 7) {
		return nil
	}
	r, rok := number(radiant, "m_iHeroKills")
	d, dok := number(dire, "m_iHeroKills")
	rt, rteam := number(radiant, "m_iTeamNum")
	dt, dteam := number(dire, "m_iTeamNum")
	if !rok || !dok || !rteam || !dteam || rt != 2 || dt != 3 || r < 0 || d < 0 {
		return nil
	}
	return &snapshot{Fields: map[string]interface{}{"radiant_score": int(r), "dire_score": int(d)},
		Provenance: map[string]string{"radiant_score": "CDOTATeam.m_iHeroKills; m_iTeamNum=2; first post-game packet", "dire_score": "CDOTATeam.m_iHeroKills; m_iTeamNum=3; first post-game packet"}, Tick: tick, State: int(state)}
}
func enrichRules(s *snapshot, rules getter) {
	if s == nil || rules == nil {
		return
	}
	if _, present := s.Fields["duration"]; !present {
		start, sok := rule(rules, "m_flGameStartTime")
		end, eok := rule(rules, "m_flGameEndTime")
		if sok && eok && end > 0 && end >= start {
			s.Fields["duration"] = end - start
			s.Fields["game_start"] = start
			s.Fields["game_end"] = end
			s.Provenance["duration"] = "CDOTAGamerulesProxy: m_flGameEndTime - m_flGameStartTime (recorded game clock; not playback time)"
		}
	}
	if lobby, ok := rule(rules, "m_lobbyType"); ok && lobby >= 0 && lobby == math.Trunc(lobby) {
		if _, present := s.Fields["lobby_type"]; !present {
			s.Fields["lobby_type"] = int(lobby)
			s.Provenance["lobby_type"] = "CDOTAGamerulesProxy.m_pGameRules.m_lobbyType (recorded lobby enum)"
		}
	}
}

type countedReader struct {
	io.Reader
	bytes, total int64
	encoder      *json.Encoder
	last         time.Time
}

func (r *countedReader) Read(p []byte) (int, error) {
	n, err := r.Reader.Read(p)
	r.bytes += int64(n)
	if time.Since(r.last) >= 500*time.Millisecond {
		r.encoder.Encode(map[string]interface{}{"event": "progress", "bytes": r.bytes, "total_bytes": r.total, "fraction": float64(r.bytes) / float64(max(r.total, 1))})
		r.last = time.Now()
	}
	return n, err
}

func parse(path string, probe bool, encoder *json.Encoder) (result map[string]interface{}) {
	result = map[string]interface{}{"event": "result", "schema_version": 1, "helper_version": Version, "complete": false}
	start := time.Now()
	defer func() {
		result["elapsed_seconds"] = time.Since(start).Seconds()
		if recovered := recover(); recovered != nil {
			result["error"] = fmt.Sprint(recovered)
			result["complete"] = false
		}
	}()
	f, err := os.Open(path)
	if err != nil {
		result["error"] = err.Error()
		return
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		result["error"] = err.Error()
		return
	}
	reader := &countedReader{Reader: f, total: info.Size(), encoder: encoder, last: time.Now()}
	p, err := manta.NewStreamParser(reader)
	if err != nil {
		result["error"] = err.Error()
		return
	}
	graph := newGraphState()
	attachGraph(p, graph)
	var rules *manta.Entity
	var players getter
	chatCount := 0
	emitChat := func(entry map[string]interface{}) error {
		if entry == nil {
			return nil
		}
		if rules != nil {
			now, nok := graphClock(rules, graph.netTick, graph.tickInterval)
			start, sok := rule(rules, "m_flGameStartTime")
			if nok && sok && start > 0 {
				entry["time"] = now - start
			}
		}
		chatCount++
		return encoder.Encode(map[string]interface{}{"event": "chat", "entry": entry})
	}
	p.Callbacks.OnCUserMessageSayText2(func(message *dota.CUserMessageSayText2) error {
		return emitChat(sayText(message, p.Tick))
	})
	p.Callbacks.OnCDOTAUserMsg_ChatMessage(func(message *dota.CDOTAUserMsg_ChatMessage) error {
		return emitChat(dotaChat(message, players, p.Tick))
	})
	teams := map[int]*manta.Entity{}
	var final *snapshot
	identity := map[string]interface{}{}
	p.Callbacks.OnCDemoFileInfo(func(info *dota.CDemoFileInfo) error {
		game := info.GetGameInfo().GetDota()
		if game == nil {
			return nil
		}
		if game.GetMatchId() > 0 {
			identity["match_id"] = fmt.Sprint(game.GetMatchId())
		}
		if game.GetLeagueid() > 0 {
			identity["league_id"] = game.GetLeagueid()
		}
		if game.GetGameMode() > 0 {
			identity["game_mode"] = game.GetGameMode()
		}
		if game.GetGameWinner() == 2 || game.GetGameWinner() == 3 {
			identity["winner"] = game.GetGameWinner()
		}
		if game.GetEndTime() > 0 {
			identity["end_time"] = game.GetEndTime()
		}
		players := []map[string]interface{}{}
		for _, player := range game.GetPlayerInfo() {
			steam := player.GetSteamid()
			var account interface{}
			if !player.GetIsFakeClient() && steam > 76561197960265728 && steam < 76561197960265728+1<<32 {
				account = steam - 76561197960265728
			}
			players = append(players, map[string]interface{}{"steam_id": fmt.Sprint(steam), "account_id": account, "name": player.GetPlayerName(), "hero": strings.TrimPrefix(player.GetHeroName(), "npc_dota_hero_"), "team": player.GetGameTeam()})
		}
		if len(players) > 0 {
			identity["players"] = players
		}
		return nil
	})
	probes := map[string]map[string]interface{}{}
	p.OnEntity(func(e *manta.Entity, op manta.EntityOp) error {
		class := e.GetClassName()
		if (class == "CDOTA_PlayerResource" || class == "C_DOTA_PlayerResource") && !op.Flag(manta.EntityOpDeleted) {
			players = e
		}
		isRules := strings.Contains(strings.ToLower(class), "gamerules")
		isTeam := class == "CDOTATeam" || class == "C_DOTATeam"
		if (!isRules && !isTeam) || op.Flag(manta.EntityOpDeleted) {
			return nil
		}
		if isRules {
			rules = e
		}
		if isTeam {
			if team, ok := number(e, "m_iTeamNum"); ok && (team == 2 || team == 3) {
				teams[int(team)] = e
			}
		}
		// Manta dispatches after the whole packet was decoded: current team objects
		// include that packet's final counters. Freeze once at the first post-game.
		if final == nil && rules != nil && teams[2] != nil && teams[3] != nil {
			final = capture(rules, teams[2], teams[3], p.Tick)
		}
		if final != nil {
			enrichRules(final, rules)
		}
		if probe {
			data := map[string]interface{}{}
			for k, v := range e.Map() {
				low := strings.ToLower(k)
				for _, pattern := range []string{"score", "kills", "gametime", "starttime", "endtime", "gamestate", "lobby", "teamnum"} {
					if strings.Contains(low, pattern) {
						data[k] = v
						break
					}
				}
			}
			probes[fmt.Sprintf("%s:%d", class, e.GetIndex())] = data
		}
		return nil
	})
	err = p.Start()
	result["engine_build"] = p.GameBuild
	result["processed_bytes"] = reader.bytes
	if probe {
		result["compatibility_fields"] = probes
	}
	if err != nil {
		result["error"] = err.Error()
		return
	}
	if final == nil {
		result["error"] = "Recording has no authoritative post-game team score snapshot"
		result["status"] = "incomplete"
		return
	}
	result["complete"] = true
	result["chat_complete"] = true
	result["chat_count"] = chatCount
	for field, value := range identity {
		final.Fields[field] = value
		final.Provenance[field] = "CDemoFileInfo typed Dota summary (recorded identity)"
	}
	result["fields"] = final.Fields
	result["provenance"] = final.Provenance
	result["final_tick"] = final.Tick
	result["final_state"] = final.State
	if err := graph.emit(encoder, result); err != nil {
		result["complete"] = false
		result["error"] = err.Error()
	}
	return
}
func run() error {
	probe := flag.Bool("probe", false, "Include selected field maps for developer compatibility checks")
	graph := flag.Bool("graph-probe", false, "Development-only graph feasibility JSON (separate from app protocol)")
	version := flag.Bool("version", false, "Print helper version")
	flag.Parse()
	if *version {
		fmt.Println(Version)
		return nil
	}
	if flag.NArg() != 1 {
		return errors.New("one local replay path required")
	}
	encoder := json.NewEncoder(os.Stdout)
	if *graph {
		result := graphProbe(flag.Arg(0))
		if err := encoder.Encode(result); err != nil {
			return err
		}
		if complete, _ := result["complete"].(bool); !complete {
			return errors.New("graph probe incomplete")
		}
		return nil
	}
	result := parse(flag.Arg(0), *probe, encoder)
	encoder.Encode(result)
	if complete, _ := result["complete"].(bool); !complete {
		return errors.New("local replay parse did not complete")
	}
	return nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
