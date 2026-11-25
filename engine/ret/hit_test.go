package main

import (
	"encoding/json"
	"github.com/wowsims/forever/sim"
	"github.com/wowsims/forever/sim/core"
	"github.com/wowsims/forever/sim/core/proto"
	"github.com/wowsims/forever/sim/siml"
	"google.golang.org/protobuf/encoding/protojson"
	gp "google.golang.org/protobuf/proto"
	"os"
	"testing"
)

func TestNativeRetMeleeHitChangesMissesAndCaps(t *testing.T) {
	sim.RegisterAll()
	data, err := os.ReadFile("../../bundle/defaults.json")
	if err != nil {
		t.Fatal(err)
	}
	var presets map[string]json.RawMessage
	if err = json.Unmarshal(data, &presets); err != nil {
		t.Fatal(err)
	}
	s := &proto.IndividualSimSettings{}
	if err = protojson.Unmarshal(presets["ret"], s); err != nil {
		t.Fatal(err)
	}
	p := s.Player
	p.EnableItemSwap = false
	p.ItemSwap = nil
	p.InFrontOfTarget = false
	p.Consumables = &proto.ConsumesSpec{}
	apl, err := siml.ReadFile("../upstream/ui/specs/paladin/retribution/apls/default.apl.siml")
	if err != nil {
		t.Fatal(err)
	}
	p.Rotation = apl.Rotation()
	encounter := s.Encounter
	encounter.Duration = 180
	encounter.DurationVariation = 0
	encounter.Targets[0].Level = 63
	raid := core.SinglePlayerRaidProto(p, s.PartyBuffs, s.RaidBuffs, s.Debuffs)
	computed := core.ComputeStats(&proto.ComputeStatsRequest{Raid: raid, Encounter: encounter})
	if computed.ErrorResult != "" {
		t.Fatal(computed.ErrorResult)
	}
	original := computed.RaidStats.Parties[0].Players[0].FinalStats.PseudoStats[12]
	var damage []float64
	var misses []int32
	for _, hit := range []float64{0, 4, 8, 12} {
		r := gp.Clone(raid).(*proto.Raid)
		r.Parties[0].Players[0].BonusStats = &proto.UnitStats{Stats: make([]float64, len(proto.Stat_name)), PseudoStats: make([]float64, len(proto.PseudoStat_name))}
		r.Parties[0].Players[0].BonusStats.PseudoStats[12] = hit - original
		result := core.RunRaidSim(&proto.RaidSimRequest{Raid: r, Encounter: encounter, SimOptions: &proto.SimOptions{Iterations: 1000, RandomSeed: 17012026}})
		if result.Error != nil {
			t.Fatal(result.Error.Message)
		}
		var count int32
		for _, action := range result.RaidMetrics.Parties[0].Players[0].Actions {
			if action.Id.GetOtherId() == proto.OtherAction_OtherActionAttack {
				for _, target := range action.Targets {
					count += target.Misses
				}
			}
		}
		dps := result.RaidMetrics.Dps.Avg
		damage = append(damage, dps)
		misses = append(misses, count)
		t.Logf("melee hit %.1f%%: %.3f DPS, %d auto misses", hit, dps, count)
	}
	if !(misses[0] > misses[1] && misses[1] > 0 && misses[2] == 0 && misses[3] == 0) {
		t.Fatalf("unexpected miss counts %v", misses)
	}
	if damage[2] <= damage[0] {
		t.Fatal("hit below the cap did not improve DPS")
	}
	if damage[2] != damage[3] {
		t.Fatal("melee hit above the cap changed this fixed-seed result")
	}
}
