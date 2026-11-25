# GuildSim

WoW Forever guild addon and Windows helper, distributed separately from other projects on this account.

**[Download the installer](https://github.com/bryan970/guildsim/releases/latest/download/GuildSim-Setup.exe)** · [Release notes](https://github.com/bryan970/guildsim/releases/latest)

Current release: **0.2.0-beta.2**. Ready for guild beta acceptance testing; Priest remains a stats planner. Use this installer instead of the earlier 0.1 ZIP.

## Install once

1. Ret users: install [GearMatic](https://www.curseforge.com/wow/addons/gearmatic) first. GuildSim preserves it.
2. Run **GuildSim-Setup.exe**. No Python, compiler, admin account or GitHub account is required.
3. Close WoW once. The helper detects a standard Forever installation; otherwise select `_forever_` once.
4. Enable **GuildSim Beta** and **WowSimsExporter**, then use `/guildsim` → **Update sims** → `/reload`.
5. Keep playing while the helper runs. Reload again when results are ready.

The helper can start with Windows. Closing its window leaves it running; reopen the GuildSim shortcut for progress or use **Quit helper** to stop it.

## Updates

Updates to the addon, helper and pinned engine come together through this repository's public releases. The helper checks on startup and every 30 minutes, verifies the release signature and checksums, tests the download, and waits for WoW and simulations to close before switching. A preceding version is retained for startup recovery. Character data is stored outside program files and is never uploaded.

## Profiles

| Profile | Races | Status |
|---|---|---|
| Retribution Paladin | Human, Dwarf, Undead | Native DPS, stat weights, gear and weapon/enchant comparisons, catalogs and trinket combinations; Unsealed Wrath build |
| Discipline raid-healer Priest | Human, Dwarf, Night Elf, Gnome, Undead, Troll | **Stats planner only**: healing power, mana, regen and crit; no HPS simulation |

Ret includes character-pane browsing, GearMatic imports and Forever stat handling, fixed catalog reference trinkets, independently simulated trinket pairs in both orders, creature-type/family profiles, Rune of the Dawn against Undead, partial-model/confidence labels, resumable native caches, custom farming targets, separate target-set weights and a local SQLite fight library. Leveling projections are labeled as level-60 models.

## Move an existing personal Ret setup

Choose the Ret character and **Move personal setup** in the helper. Select the old helper folder containing `config.json` and `output`. Settings, farming targets, reference trinkets, remembered pools, saved requests and fight history are copied locally. GuildSim validates its workflow before handoff and waits for the existing helper's active work to finish. Original helper files and SavedVariables remain available for rollback.

## Beta limits

In-game guild acceptance testing is required. Native item-effect coverage is incomplete; partial-model and statistical-error labels remain visible. The Priest profile does not rank healing performance. GearMatic is a separate prerequisite and is not bundled or modified. The Windows installer is not Authenticode signed; update metadata uses a separate Ed25519 release signature.

## Source and credits

The release archive includes GuildSim source and dependency notices. Native engine: [WoWSims Forever](https://github.com/wowsims/forever), pinned to v1.0.4, commit `a8bd7fd83a3a7c5102012ed87d86a71d175b3a89`. Exporter: [WowSimsExporter](https://github.com/wowsims/exporter). Both retain their MIT notices. GuildSim-owned code is MIT licensed. GearMatic retains its own license.

Not affiliated with Blizzard, WoWSims or GearMatic.
