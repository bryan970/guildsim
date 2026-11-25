// Package healsim adds declared healing assignments to the pinned native engine.
// Spell ranks, talents, costs, cooldowns, procs and item effects remain native.
package healsim

import (
	"fmt"
	"github.com/wowsims/forever/sim/core"
	"github.com/wowsims/forever/sim/core/dbcenums"
	"github.com/wowsims/forever/sim/core/proto"
	"github.com/wowsims/forever/sim/core/simsignals"
	"github.com/wowsims/forever/sim/core/spelldata"
	"github.com/wowsims/forever/sim/core/stats"
	"github.com/wowsims/forever/sim/priest"
	"github.com/wowsims/forever/sim/priest/healer"
	gp "google.golang.org/protobuf/proto"
	"math"
	"math/rand/v2"
	"sort"
	"time"
)

const ModelVersion = "guildsim-disc-assignment-1"

type Scenario struct {
	Assignment     string  `json:"assignment"`
	Duration       float64 `json:"duration"`
	Recipients     int     `json:"recipients"`
	Health         float64 `json:"health"`
	IncomingDPS    float64 `json:"incomingDps"`
	Seed           int64   `json:"seed"`
	DisableCasting bool    `json:"disableCasting,omitempty"` // engine validation only
}
type Result struct {
	Model                   string            `json:"healingModel"`
	UsefulHPS               float64           `json:"usefulHps"`
	EffectiveHPS            float64           `json:"effectiveHps"`
	AbsorbHPS               float64           `json:"absorbHps"`
	OverhealHPS             float64           `json:"overhealHps"`
	Stdev                   float64           `json:"stdev"`
	Error95                 float64           `json:"meanError95"`
	Survival                float64           `json:"survival"`
	ManaRemaining           float64           `json:"manaRemaining"`
	MissingHealth           float64           `json:"averageMissingHealth"`
	ScheduledIncomingDamage float64           `json:"scheduledIncomingDamage"`
	Iterations              int               `json:"iterations"`
	Casts                   map[int32]float64 `json:"casts"`
	ItemUses                map[int32]float64 `json:"itemUses"`
	Scenario                Scenario          `json:"healingScenario"`
}

func Normalize(sc Scenario) (Scenario, error) {
	if sc.Assignment == "" {
		sc.Assignment = "group"
	}
	if sc.Assignment != "group" && sc.Assignment != "tank" && sc.Assignment != "burst" {
		return sc, fmt.Errorf("unknown healing assignment")
	}
	if sc.Duration == 0 {
		sc.Duration = 180
	}
	if sc.Recipients == 0 {
		sc.Recipients = 4
	}
	if sc.Health == 0 {
		sc.Health = 18000
	}
	if sc.IncomingDPS == 0 {
		if sc.Assignment == "tank" {
			sc.IncomingDPS = 700
		} else {
			sc.IncomingDPS = 800
		}
	}
	if sc.Seed == 0 {
		sc.Seed = 58723001
	}
	if sc.Duration < 30 || sc.Duration > 900 || sc.Recipients < 1 || sc.Recipients > 4 || sc.Health < 1000 || sc.Health > 100000 || sc.IncomingDPS < 0 || sc.IncomingDPS > 10000 {
		return sc, fmt.Errorf("healing scenario outside supported bounds")
	}
	return sc, nil
}

// Run reuses one native environment and independent seeds for each fight. Only
// assigned recipients contribute healing; self heals and mana-rune damage cannot
// inflate the assignment score. Damage consumes native absorption auras.
func Run(request *proto.RaidSimRequest, scenario Scenario, iterations int) (Result, error) {
	sc, err := Normalize(scenario)
	if err != nil {
		return Result{}, err
	}
	if iterations < 1 || iterations > 10000 {
		return Result{}, fmt.Errorf("healing fights must be 1..10000")
	}
	req := gp.Clone(request).(*proto.RaidSimRequest)
	req.Raid.TargetDummies = int32(sc.Recipients)
	req.Raid.Tanks = nil
	req.Encounter.Duration = sc.Duration
	req.Encounter.DurationVariation = 0
	for _, t := range req.Encounter.Targets {
		t.SwingSpeed = 0
		t.MinBaseDamage = 0
	}
	req.SimOptions = &proto.SimOptions{Iterations: 1, RandomSeed: sc.Seed}
	assigned := []*core.Unit{}
	var incoming *core.Spell
	dead := map[*core.Unit]bool{}
	seenHealing := map[*core.ResourceMetrics]float64{}
	effectiveHealing, rawHealing := 0.0, 0.0
	sim := core.NewSimWithAssignmentSetup(req, simsignals.CreateSignals(), func(env *core.Environment) {
		for _, dummy := range env.Raid.GetTargetDummies() {
			dummy.EnableHealthBar()
			assigned = append(assigned, &dummy.Unit)
		}
		for _, unit := range assigned {
			observe := func(_ *core.Aura, _ *core.Simulation, spell *core.Spell, hit *core.SpellResult) {
				metric := spell.HealthMetrics(hit.Target)
				current := metric.ActualGainForCurrentIteration()
				gain := current - seenHealing[metric]
				seenHealing[metric] = current
				if !dead[hit.Target] {
					effectiveHealing += math.Max(0, gain)
					rawHealing += hit.Damage
				}
			}
			unit.RegisterAura(core.Aura{Label: "GuildSim assignment observer", Duration: core.NeverExpires, OnReset: func(a *core.Aura, s *core.Simulation) { a.Activate(s) }, OnHealTaken: observe, OnPeriodicHealTaken: observe})
		}
		incoming = env.Encounter.ActiveTargetUnits[0].RegisterSpell(core.SpellConfig{ActionID: core.ActionID{OtherID: proto.OtherAction_OtherActionDamageTaken}, SpellSchool: core.SpellSchoolPhysical, ProcMask: core.ProcMaskEmpty, Flags: core.SpellFlagIgnoreModifiers | core.SpellFlagIgnoreResists, DamageMultiplier: 1, ThreatMultiplier: 0})
	})
	agent, ok := sim.Raid.Parties[0].Players[0].(*healer.HealerPriest)
	if !ok {
		return Result{}, fmt.Errorf("native healer Priest required")
	}
	byMask := map[int64][]*core.Spell{}
	for _, spell := range agent.Spellbook {
		if spell.Cost != nil && !spell.Flags.Matches(core.SpellFlagPassiveSpell) {
			byMask[spell.ClassSpellMask] = append(byMask[spell.ClassSpellMask], spell)
		}
	}
	for _, spells := range byMask {
		sort.Slice(spells, func(i, j int) bool { return spells[i].Rank > spells[j].Rank })
	}
	friendlyItems := map[*core.Spell]bool{}
	result := Result{Model: ModelVersion, Iterations: iterations, Scenario: sc, Casts: map[int32]float64{}, ItemUses: map[int32]float64{}}
	sumSquares := 0.0
	for iteration := 0; iteration < iterations; iteration++ {
		damageRNG := rand.New(rand.NewPCG(uint64(sc.Seed)+uint64(iteration)*104729, 0x4755494c4453494d))
		sim.Reseed(sc.Seed + int64(iteration)*104729)
		sim.Reset()
		if iteration == 0 {
			for _, cd := range agent.GetMajorCooldowns() {
				item := core.GetItemByID(cd.Spell.ActionID.ItemID)
				if item == nil {
					continue
				}
				for _, effect := range item.ItemEffects {
					if effect.GetOnUse() == nil {
						continue
					}
					row := spelldata.Find(effect.BuffId)
					if row == nil {
						continue
					}
					for _, e := range row.Effects {
						if e.Type != dbcenums.E_HEAL && e.Type != dbcenums.E_HEAL_PCT {
							continue
						}
						for _, target := range e.Target {
							if target == dbcenums.TARGET_UNIT_TARGET_ALLY || target == dbcenums.TARGET_UNIT_TARGET_PARTY || target == dbcenums.TARGET_UNIT_TARGET_RAID {
								friendlyItems[cd.Spell] = true
							}
						}
					}
				}
			}
		}
		sim.PrePull()
		for _, unit := range assigned {
			unit.AddStatsDynamic(sim, stats.Stats{stats.Health: sc.Health - unit.MaxHealth()})
			unit.SetCurrentHealthPercent(1)
		}
		dead = map[*core.Unit]bool{}
		seenHealing = map[*core.ResourceMetrics]float64{}
		effectiveHealing = 0
		rawHealing = 0
		missingSum := 0.0
		ticks := 0
		consumedShields := 0.0
		scheduledDamage := 0.0
		var damageTick func(*core.Simulation)
		damageTick = func(s *core.Simulation) {
			ticks++
			for index, unit := range assigned {
				amount := sc.IncomingDPS / float64(sc.Recipients)
				if sc.Assignment == "tank" {
					if index == 0 {
						amount = sc.IncomingDPS
					} else {
						amount = 0
					}
				}
				if sc.Assignment == "burst" {
					if int(s.CurrentTime/time.Second)%12 == 0 {
						amount *= 8
					} else {
						amount *= .35
					}
				}
				amount *= .8 + .4*damageRNG.Float64()
				scheduledDamage += amount
				if dead[unit] {
					missingSum += unit.MaxHealth()
					continue
				}
				hit := incoming.CalcDamage(s, unit, amount, incoming.OutcomeAlwaysHit)
				consumedShields += math.Max(0, amount-hit.Damage)
				// Native target dummies have no chance-of-death tracker. Apply only the
				// post-absorb remainder to their health, once, before dispatching hit procs.
				unit.RemoveHealth(s, hit.Damage)
				incoming.DealDamage(s, hit)
				if unit.CurrentHealth() <= 0 {
					dead[unit] = true
				}
				missingSum += unit.MaxHealth() - unit.CurrentHealth()
			}
			if s.CurrentTime+time.Second < s.Duration {
				s.AddPendingAction(&core.PendingAction{NextActionAt: s.CurrentTime + time.Second, OnAction: damageTick})
			}
		}
		var decide func(*core.Simulation)
		decide = func(s *core.Simulation) {
			if !sc.DisableCasting && agent.CurrentHealth() > 0 {
				var target *core.Unit
				for _, unit := range assigned {
					if !dead[unit] && (target == nil || unit.CurrentHealthPercent() < target.CurrentHealthPercent()) {
						target = unit
					}
				}
				if target != nil {
					deficit := target.MaxHealth() - target.CurrentHealth()
					for _, cd := range agent.GetMajorCooldowns() {
						if friendlyItems[cd.Spell] {
							if deficit >= 1200 && cd.Spell.CanCast(s, target) {
								cd.Spell.Cast(s, target)
							}
							continue
						}
						mana := cd.Type.Matches(core.CooldownTypeMana)
						if mana && agent.MaxMana()-agent.CurrentMana() < 1200 {
							continue
						}
						if mana || cd.Type.Matches(core.CooldownTypeHealing) || cd.BuffAura != nil || cd.Spell.ActionID.SpellID == 10060 || cd.Spell.ActionID.SpellID == 26297 {
							cd.TryActivate(s, &agent.Character)
						}
					}
					// Native CanCast enforces hardcast/channel/GCD, talents, mana and cooldowns.
					masks := []int64{priest.PriestSpellPowerWordShield, priest.PriestSpellPenance, priest.PriestSpellRenew, priest.PriestSpellGreaterHeal, priest.PriestSpellFlashHeal, priest.PriestSpellHeal}
					for _, mask := range masks {
						if mask == priest.PriestSpellRenew && deficit < 500 {
							continue
						}
						if mask != priest.PriestSpellPowerWordShield && deficit < 1200 {
							continue
						}
						cast := false
						for _, spell := range byMask[mask] {
							if mask == priest.PriestSpellRenew && spell.Hot(target) != nil && spell.Hot(target).IsActive() {
								break
							}
							if spell.CanCast(s, target) && spell.Cast(s, target) {
								cast = true
								break
							}
						}
						if cast {
							break
						}
					}
				}
			}
			if s.CurrentTime+100*time.Millisecond < s.Duration {
				s.AddPendingAction(&core.PendingAction{NextActionAt: s.CurrentTime + 100*time.Millisecond, OnAction: decide})
			}
		}
		sim.AddPendingAction(&core.PendingAction{NextActionAt: time.Second, OnAction: damageTick})
		sim.AddPendingAction(&core.PendingAction{NextActionAt: 100 * time.Millisecond, OnAction: decide})
		for !sim.Step() {
		}
		effective, raw, absorbed := effectiveHealing, rawHealing, consumedShields
		for _, spell := range agent.Spellbook {
			for _, unit := range assigned {
				m := spell.SpellMetrics[unit.UnitIndex]
				if m.Casts > 0 {
					if spell.ActionID.ItemID > 0 {
						result.ItemUses[spell.ActionID.ItemID] += float64(m.Casts) / float64(iterations)
					} else {
						result.Casts[spell.ActionID.SpellID] += float64(m.Casts) / float64(iterations)
					}
				}
			}
		}
		useful := (effective + absorbed) / sc.Duration
		result.UsefulHPS += useful / float64(iterations)
		sumSquares += useful * useful
		result.EffectiveHPS += effective / sc.Duration / float64(iterations)
		result.AbsorbHPS += absorbed / sc.Duration / float64(iterations)
		result.OverhealHPS += math.Max(0, raw-effective) / sc.Duration / float64(iterations)
		result.ManaRemaining += agent.CurrentMana() / float64(iterations)
		result.ScheduledIncomingDamage += scheduledDamage / float64(iterations)
		if len(dead) == 0 && agent.CurrentHealth() > 0 {
			result.Survival += 1 / float64(iterations)
		}
		if ticks > 0 {
			result.MissingHealth += missingSum / float64(ticks) / float64(iterations)
		}
		sim.Cleanup()
	}
	if iterations > 1 {
		result.Stdev = math.Sqrt(math.Max(0, (sumSquares-float64(iterations)*result.UsefulHPS*result.UsefulHPS)/float64(iterations-1)))
		result.Error95 = 1.96 * result.Stdev / math.Sqrt(float64(iterations))
	}
	return result, nil
}
