package healsim_test

import (
	"encoding/json"
	"github.com/wowsims/forever/sim"
	"github.com/wowsims/forever/sim/core"
	"github.com/wowsims/forever/sim/core/proto"
	"google.golang.org/protobuf/encoding/protojson"
	gp "google.golang.org/protobuf/proto"
	"guildsim/beta/healsim"
	"os"
	"testing"
)

func request(t *testing.T) *proto.RaidSimRequest {
	t.Helper()
	sim.RegisterAll()
	raw, e := os.ReadFile("../../bundle/defaults.json")
	if e != nil {
		t.Fatal(e)
	}
	var presets map[string]json.RawMessage
	if e = json.Unmarshal(raw, &presets); e != nil {
		t.Fatal(e)
	}
	p := &proto.Player{}
	if e = protojson.Unmarshal(presets["disc"], p); e != nil {
		t.Fatal(e)
	}
	return &proto.RaidSimRequest{Raid: core.SinglePlayerRaidProto(p, &proto.PartyBuffs{}, &proto.RaidBuffs{}, &proto.Debuffs{}), Encounter: &proto.Encounter{Duration: 180, Targets: []*proto.Target{{Level: 63, Stats: make([]float64, len(proto.Stat_name))}}}, SimOptions: &proto.SimOptions{Iterations: 1, RandomSeed: 1}}
}
func TestHealingAssignmentHasRealHealingAndConsumedAbsorbs(t *testing.T) {
	r, e := healsim.Run(request(t), healsim.Scenario{Assignment: "group", Duration: 180}, 4)
	if e != nil {
		t.Fatal(e)
	}
	t.Logf("native result: %+v", r)
	if r.UsefulHPS <= 0 || r.EffectiveHPS <= 0 || r.AbsorbHPS <= 0 {
		t.Fatal("expected direct healing and consumed shields")
	}
	if r.UsefulHPS > 1000 {
		t.Fatal("assignment healing exceeds supplied damage")
	}
	if r.ManaRemaining < 0 || r.Survival < 0 || r.Survival > 1 {
		t.Fatal("invalid resource or survival result")
	}
}
func TestNoCastingCannotGenerateHealing(t *testing.T) {
	r, e := healsim.Run(request(t), healsim.Scenario{Assignment: "group", Duration: 180, DisableCasting: true}, 2)
	if e != nil {
		t.Fatal(e)
	}
	if r.UsefulHPS != 0 || r.EffectiveHPS != 0 || r.AbsorbHPS != 0 {
		t.Fatalf("healing without casts: %+v", r)
	}
	if r.Survival != 0 {
		t.Fatal("unhealed assigned recipients should die")
	}
}
func TestFixedSeedsReproduceNativeFightResults(t *testing.T) {
	a, e := healsim.Run(request(t), healsim.Scenario{Assignment: "tank", Duration: 90, IncomingDPS: 350}, 3)
	if e != nil {
		t.Fatal(e)
	}
	b, e := healsim.Run(request(t), healsim.Scenario{Assignment: "tank", Duration: 90, IncomingDPS: 350}, 3)
	if e != nil {
		t.Fatal(e)
	}
	if a.UsefulHPS != b.UsefulHPS || a.Survival != b.Survival || a.ManaRemaining != b.ManaRemaining {
		t.Fatal("same input and seeds changed the outcome")
	}
}
func TestUnusedShieldsCannotCreateUsefulHealing(t *testing.T) {
	r, e := healsim.Run(request(t), healsim.Scenario{Assignment: "group", Duration: 60, IncomingDPS: 0.000001}, 2)
	if e != nil {
		t.Fatal(e)
	}
	if r.UsefulHPS > 0.000002 || r.EffectiveHPS > 0 {
		t.Fatalf("shield credit without damage: %+v", r)
	}
}

func TestIncomingDamageDoesNotDependOnCastingOrDeaths(t *testing.T) {
	a, e := healsim.Run(request(t), healsim.Scenario{Assignment: "group", Duration: 180}, 3)
	if e != nil {
		t.Fatal(e)
	}
	b, e := healsim.Run(request(t), healsim.Scenario{Assignment: "group", Duration: 180, DisableCasting: true}, 3)
	if e != nil {
		t.Fatal(e)
	}
	if a.ScheduledIncomingDamage != b.ScheduledIncomingDamage {
		t.Fatal("casting or survival changed the comparison workload")
	}
}

func TestNativeHealingPowerChangesFightOutcomes(t *testing.T) {
	low := request(t)
	high := gp.Clone(low).(*proto.RaidSimRequest)
	bonus := make([]float64, len(proto.Stat_name))
	bonus[proto.Stat_StatHealingPower] = 1000
	high.Raid.Parties[0].Players[0].BonusStats = &proto.UnitStats{Stats: bonus}
	a, e := healsim.Run(low, healsim.Scenario{Assignment: "group", Duration: 180}, 8)
	if e != nil {
		t.Fatal(e)
	}
	b, e := healsim.Run(high, healsim.Scenario{Assignment: "group", Duration: 180}, 8)
	if e != nil {
		t.Fatal(e)
	}
	if b.UsefulHPS <= a.UsefulHPS {
		t.Fatalf("native healing power did not improve useful healing: %.2f -> %.2f", a.UsefulHPS, b.UsefulHPS)
	}
	if a.ScheduledIncomingDamage != b.ScheduledIncomingDamage {
		t.Fatal("gear sensitivity changed incoming damage")
	}
}

func TestFriendlyHealingItemTargetsTheAssignment(t *testing.T) {
	req := request(t)
	p := req.Raid.Parties[0].Players[0]
	p.Profession1 = proto.Profession_Engineering
	p.Equipment.Items[12] = &proto.ItemSpec{Id: 18637}
	r, e := healsim.Run(req, healsim.Scenario{Assignment: "tank", Duration: 180, IncomingDPS: 350}, 4)
	if e != nil {
		t.Fatal(e)
	}
	if r.ItemUses[18637] <= 0 {
		t.Fatal("equipped friendly heal item was not used on assigned recipients")
	}
}
