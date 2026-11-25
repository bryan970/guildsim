// Guild beta adapter. Native spells plus the additive friendly-assignment hook.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"guildsim/beta/healsim"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/wowsims/forever/sim"
	"github.com/wowsims/forever/sim/core"
	"github.com/wowsims/forever/sim/core/proto"
	"github.com/wowsims/forever/sim/siml"
	"google.golang.org/protobuf/encoding/protojson"
	gp "google.golang.org/protobuf/proto"
)

type Character struct {
	Flavor      string          `json:"flavor"`
	Class       string          `json:"class"`
	Race        string          `json:"race"`
	Name        string          `json:"name"`
	Level       int             `json:"level"`
	Talents     string          `json:"talents"`
	Gear        json.RawMessage `json:"gear"`
	Professions []struct {
		Name string `json:"name"`
	} `json:"professions"`
}
type Candidate struct {
	Key  string          `json:"key"`
	Gear json.RawMessage `json:"gear"`
}
type Input struct {
	Profile        string           `json:"profile"`
	Character      Character        `json:"character"`
	Iterations     int32            `json:"iterations"`
	Duration       float64          `json:"duration"`
	MobType        int32            `json:"mobType"`
	CreatureFamily int32            `json:"creatureFamily"`
	Candidates     []Candidate      `json:"candidates"`
	Reference      json.RawMessage  `json:"reference"`
	Scenario       json.RawMessage  `json:"scenario"`
	Healing        healsim.Scenario `json:"healing"`
	SkipBaseline   bool             `json:"skipBaseline"`
}

func must(err error) {
	if err != nil {
		panic(err)
	}
}
func raw(p gp.Message) json.RawMessage { b, e := protojson.Marshal(p); must(e); return b }
func load(b []byte, p gp.Message)      { must(protojson.Unmarshal(b, p)) }
func norm(s string) string {
	return strings.ToLower(strings.NewReplacer(" ", "", "_", "", "-", "").Replace(s))
}
func statValues(p *proto.PlayerStats) map[string]float64 {
	out := map[string]float64{}
	for i, v := range p.FinalStats.Stats {
		out[strings.TrimPrefix(proto.Stat_name[int32(i)], "Stat")] = v
	}
	for i, v := range p.FinalStats.PseudoStats {
		out[strings.TrimPrefix(proto.PseudoStat_name[int32(i)], "PseudoStat")] = v
	}
	return out
}
func main() {
	defer func() {
		if e := recover(); e != nil {
			fmt.Fprintln(os.Stderr, "GuildSim:", e)
			os.Exit(1)
		}
	}()
	runtime.GOMAXPROCS(2)
	prepare := flag.String("prepare", "", "source root; write public native presets")
	defaults := flag.String("defaults", "defaults.json", "public defaults")
	input := flag.String("input", "", "request JSON")
	output := flag.String("output", "", "response JSON")
	capabilities := flag.Bool("capabilities", false, "print native race registry")
	flag.Parse()
	sim.RegisterAll()
	if *capabilities {
		caps := map[string][]string{}
		for _, c := range []proto.Class{proto.Class_ClassPaladin, proto.Class_ClassPriest} {
			for _, r := range core.ClassRaceCapabilities[c] {
				caps[strings.TrimPrefix(c.String(), "Class")] = append(caps[strings.TrimPrefix(c.String(), "Class")], strings.TrimPrefix(r.String(), "Race"))
			}
		}
		b, e := json.MarshalIndent(caps, "", "  ")
		must(e)
		fmt.Println(string(b))
		return
	}
	if *prepare != "" {
		base := filepath.Join(*prepare, "ui/specs/paladin/retribution")
		f, e := siml.ReadFile(filepath.Join(base, "defaults.siml"))
		must(e)
		s := f.Settings
		apl, e := siml.ReadFile(filepath.Join(base, "apls/default.apl.siml"))
		must(e)
		s.Player.Rotation = apl.Rotation()
		s.Player.Rotation.Type = proto.APLRotation_TypeAPL
		gear, e := os.ReadFile(filepath.Join(*prepare, "ui/specs/priest/healer/gear_sets/preraid.gear.json"))
		must(e)
		priest := &proto.Player{Name: "Public preset", Class: proto.Class_ClassPriest, Race: proto.Race_RaceDwarf, TalentsString: "005025021330011531-335001030301", Equipment: &proto.EquipmentSpec{}, Rotation: &proto.APLRotation{}}
		var g map[string]json.RawMessage
		must(json.Unmarshal(gear, &g))
		delete(g, "version")
		gear, e = json.Marshal(g)
		must(e)
		load(gear, priest.Equipment)
		priest.Spec = &proto.Player_HealerPriest{HealerPriest: &proto.HealerPriest{Options: &proto.HealerPriest_Options{ClassOptions: &proto.PriestOptions{}, PrayerOfMendingJumps: 5, HolyNovaHealTargets: 5}}}
		b, e := json.MarshalIndent(map[string]any{"ret": raw(s), "disc": raw(priest)}, "", "  ")
		must(e)
		must(os.WriteFile(*defaults, b, 0644))
		return
	}
	b, e := os.ReadFile(*input)
	must(e)
	var in Input
	must(json.Unmarshal(b, &in))
	if in.Profile != "ret" && in.Profile != "disc-raid" {
		panic("unsupported profile")
	}
	if in.Character.Flavor != "forever" || in.Character.Level != 60 {
		panic("Forever level 60 export required")
	}
	class := proto.Class_ClassPaladin
	if in.Profile == "disc-raid" {
		class = proto.Class_ClassPriest
	}
	if norm(in.Character.Class) != norm(strings.TrimPrefix(class.String(), "Class")) {
		panic("profile does not match character class")
	}
	var race proto.Race
	for _, r := range core.ClassRaceCapabilities[class] {
		if norm(strings.TrimPrefix(r.String(), "Race")) == norm(in.Character.Race) {
			race = r
		}
	}
	if race == proto.Race_RaceUnknown {
		panic("unsupported race/class combination")
	}
	if in.Character.Talents == "" || in.Character.Talents == "--" {
		panic("export has no talents")
	}
	if in.Profile == "disc-raid" {
		points := 0
		for _, c := range strings.Split(in.Character.Talents, "-")[0] {
			if c < '0' || c > '5' {
				panic("invalid talents")
			}
			points += int(c - '0')
		}
		if points < 31 {
			panic("Discipline profile requires at least 31 Discipline talent points")
		}
	}
	if in.Iterations < 20 || in.Iterations > 50000 {
		panic("iterations must be 20..50000")
	}
	if in.Duration < 30 || in.Duration > 900 {
		panic("duration must be 30..900 seconds")
	}
	if _, ok := proto.MobType_name[in.MobType]; !ok {
		panic("invalid creature type")
	}
	if _, ok := proto.CreatureFamily_name[in.CreatureFamily]; !ok {
		panic("invalid creature family")
	}
	b, e = os.ReadFile(*defaults)
	must(e)
	var presets map[string]json.RawMessage
	must(json.Unmarshal(b, &presets))
	settings := &proto.IndividualSimSettings{}
	load(presets["ret"], settings)
	p := settings.Player
	if in.Profile == "disc-raid" {
		p = &proto.Player{}
		load(presets["disc"], p)
		settings.RaidBuffs = &proto.RaidBuffs{ArcaneIntellect: true, PowerWordFortitude: true, PrayerOfSpirit: true, MarkOfTheWild: true, MoonkinAura: true}
		settings.PartyBuffs = &proto.PartyBuffs{ManaSpringTotem: proto.TristateEffect_TristateEffectImproved, ConcentrationAura: true}
		settings.Debuffs = &proto.Debuffs{}
		p.Buffs = &proto.IndividualBuffs{GreaterBlessingOfKings: true, GreaterBlessingOfWisdom: 1}
		p.Consumables = &proto.ConsumesSpec{FlaskId: 13511, FoodId: 13931, ResourcePotId: 13444}
	}
	p.Race = race
	p.Class = class
	p.Name = in.Character.Name
	p.TalentsString = in.Character.Talents
	p.Profession1 = proto.Profession_ProfessionUnknown
	p.Profession2 = proto.Profession_ProfessionUnknown
	for i, v := range in.Character.Professions {
		if i > 1 {
			break
		}
		n, ok := proto.Profession_value[v.Name]
		if !ok {
			panic("unknown profession " + v.Name)
		}
		if i == 0 {
			p.Profession1 = proto.Profession(n)
		} else {
			p.Profession2 = proto.Profession(n)
		}
	}
	p.EnableItemSwap = false
	p.ItemSwap = nil
	// Explicit scenario overrides replace, rather than merge, the public preset assumptions.
	if len(in.Scenario) > 0 {
		var sc map[string]json.RawMessage
		must(json.Unmarshal(in.Scenario, &sc))
		for key, dst := range map[string]gp.Message{"raidBuffs": &proto.RaidBuffs{}, "partyBuffs": &proto.PartyBuffs{}, "debuffs": &proto.Debuffs{}, "buffs": &proto.IndividualBuffs{}, "consumables": &proto.ConsumesSpec{}} {
			if v, ok := sc[key]; ok {
				load(v, dst)
				switch key {
				case "raidBuffs":
					settings.RaidBuffs = dst.(*proto.RaidBuffs)
				case "partyBuffs":
					settings.PartyBuffs = dst.(*proto.PartyBuffs)
				case "debuffs":
					settings.Debuffs = dst.(*proto.Debuffs)
				case "buffs":
					p.Buffs = dst.(*proto.IndividualBuffs)
				case "consumables":
					p.Consumables = dst.(*proto.ConsumesSpec)
				}
			}
		}
	}
	setGear := func(g json.RawMessage) {
		var obj map[string]json.RawMessage
		must(json.Unmarshal(g, &obj))
		delete(obj, "version")
		v, e := json.Marshal(obj)
		must(e)
		p.Equipment = &proto.EquipmentSpec{}
		load(v, p.Equipment)
		if len(p.Equipment.Items) > 17 {
			panic("too many equipment slots")
		}
		count := 0
		for _, it := range p.Equipment.Items {
			if it != nil && it.Id != 0 {
				count++
				if core.GetItemByID(it.Id) == nil {
					panic(fmt.Sprintf("item %d is missing from this engine", it.Id))
				}
			}
		}
		if count < 12 {
			panic("at least 12 equipped items required")
		}
		if p.Profession1 != proto.Profession_Enchanting && p.Profession2 != proto.Profession_Enchanting {
			for _, slot := range []int{10, 11} {
				if len(p.Equipment.Items) > slot && p.Equipment.Items[slot] != nil {
					p.Equipment.Items[slot].Enchant = 0
				}
			}
		}
		if in.Profile == "ret" {
			eq := core.ProtoToEquipment(p.Equipment)
			if eq.MainHand().HandType != proto.HandType_HandTypeTwoHand {
				panic("Ret beta requires a two-handed main hand")
			}
		}
	}
	settings.Encounter.Duration = in.Duration
	settings.Encounter.DurationVariation = 0
	settings.Encounter.Targets = settings.Encounter.Targets[:1]
	target := settings.Encounter.Targets[0]
	target.MobType = proto.MobType(in.MobType)
	target.CreatureFamily = proto.CreatureFamily(in.CreatureFamily)
	target.ParryHaste = false
	raid := core.SinglePlayerRaidProto(p, settings.PartyBuffs, settings.RaidBuffs, settings.Debuffs)
	req := &proto.RaidSimRequest{Raid: raid, Encounter: settings.Encounter, SimOptions: &proto.SimOptions{Iterations: in.Iterations, RandomSeed: 17012026}, Type: proto.SimType_SimTypeIndividual}
	eval := func(key string, g json.RawMessage) (row map[string]any) {
		row = map[string]any{"key": key}
		defer func() {
			if err := recover(); err != nil {
				row = map[string]any{"key": key, "error": fmt.Sprint(err)}
			}
		}()
		setGear(g)
		stats := core.ComputeStats(&proto.ComputeStatsRequest{Raid: raid, Encounter: req.Encounter})
		if stats.ErrorResult != "" {
			panic(stats.ErrorResult)
		}
		row["stats"] = statValues(stats.RaidStats.Parties[0].Players[0])
		if in.Profile == "ret" {
			result := core.RunRaidSim(req)
			if result.Error != nil {
				panic(result.Error)
			}
			m := result.RaidMetrics.Parties[0].Players[0]
			if m.Dps.Avg <= 0 {
				panic("native result has no damage")
			}
			row["dps"] = m.Dps.Avg
			row["stdev"] = m.Dps.Stdev
			row["secondsOom"] = m.SecondsOomAvg
		} else {
			sc := in.Healing
			sc.Duration = in.Duration
			healingResult, err := healsim.Run(req, sc, int(in.Iterations))
			must(err)
			encoded, err := json.Marshal(healingResult)
			must(err)
			var values map[string]any
			must(json.Unmarshal(encoded, &values))
			for k, v := range values {
				row[k] = v
			}
		}
		return row
	}
	baseline := map[string]any{}
	if !in.SkipBaseline {
		baseline = eval("equipped", in.Character.Gear)
	}
	reference := baseline
	if !in.SkipBaseline && len(in.Reference) > 0 {
		reference = eval("reference", in.Reference)
	}
	rows := []map[string]any{}
	for _, c := range in.Candidates {
		rows = append(rows, eval(c.Key, c.Gear))
	}
	setGear(in.Character.Gear)
	response := map[string]any{"profile": in.Profile, "race": strings.TrimPrefix(race.String(), "Race"), "baseline": baseline, "reference": reference, "rows": rows, "request": raw(req), "iterations": in.Iterations, "objective": "native DPS"}
	if in.Profile == "disc-raid" {
		response["objective"] = "native effective healing plus consumed absorbs in the declared assignment"
	}
	b, e = json.MarshalIndent(response, "", "  ")
	must(e)
	must(os.WriteFile(*output, b, 0644))
}
