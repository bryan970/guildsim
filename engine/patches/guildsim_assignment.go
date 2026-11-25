// GuildSim host extension to WoWSims Forever. MIT license, see project LICENSE.
// Copy this additive file into upstream/sim/core before building the helper engine.
package core

import (
	"github.com/wowsims/forever/sim/core/proto"
	"github.com/wowsims/forever/sim/core/simsignals"
)

// NewSimWithAssignmentSetup registers declared friendly damage assignments and
// observers after spells initialize, before finalization. Existing simulation
// entry points and native spell mechanics are unchanged.
func NewSimWithAssignmentSetup(rsr *proto.RaidSimRequest, signals simsignals.Signals, setup func(*Environment)) *Simulation {
	env := &Environment{State: Created}
	env.construct(rsr.Raid, rsr.Encounter)
	raidStats := env.initialize(rsr.Raid, rsr.Encounter)
	setup(env)
	env.finalize(rsr.Raid, rsr.Encounter, raidStats, false, false)
	return newSimWithEnv(env, rsr.SimOptions, signals)
}
