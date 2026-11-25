# GuildSim

WoW Forever guild addon and Windows helper, distributed separately from other projects on this account.

**[Download the installer](https://github.com/bryan970/guildsim/releases/latest/download/GuildSim-Setup.exe)** Â· [Release notes](https://github.com/bryan970/guildsim/releases/latest)

Current release: **0.2.0-beta.5**. Ret and Discipline healing assignments are ready for guild beta acceptance testing. Use this installer instead of the earlier ZIPs.

## Install once

1. Ret users: install [GearMatic](https://www.curseforge.com/wow/addons/gearmatic) first. GuildSim preserves it.
2. Run **GuildSim-Setup.exe**. No Python, compiler, admin account or GitHub account is required.
3. Close WoW once. The helper detects a standard Forever installation; otherwise select `_forever_` once.
4. Enable **GuildSim Beta** and **WowSimsExporter**, then use `/guildsim` â†’ **Update sims** â†’ `/reload`.
5. Keep playing while the helper runs. Reload again when results are ready.

The helper can start with Windows. Closing its window leaves it running; reopen the GuildSim shortcut for progress or use **Quit helper** to stop it.

## Updates

Updates to the addon, helper and pinned engine come together through this repository's public releases. The helper checks on startup and every 30 minutes, verifies the release signature and checksums, tests the download, and waits for WoW and simulations to close before switching. A preceding version is retained for startup recovery. Character data is stored outside program files and is never uploaded.

## Profiles

| Profile | Races | Status |
|---|---|---|
| Retribution Paladin | Human, Dwarf, Undead | Native DPS, stat weights, gear and weapon/enchant comparisons, catalogs and trinket combinations; Unsealed Wrath build |
| Discipline raid-healer Priest | Human, Dwarf, Night Elf, Gnome, Undead, Troll | Native fight simulation: effective healing, consumed absorbs, survival, mana, overhealing, gear catalog and separate trinket combinations |

Ret includes character-pane browsing, GearMatic imports and Forever stat handling, fixed catalog reference trinkets, independently simulated trinket pairs in both orders, creature-type/family profiles, Rune of the Dawn against Undead, partial-model/confidence labels, resumable native caches, custom farming targets, separate target-set weights and a local SQLite fight library. Leveling projections are labeled as level-60 models.

Priests choose **Group healing**, **Tank healing**, or **Burst recovery**, and a three- or five-minute fight in `/guildsim`, then Update sims and reload. The helper runs 256 seeded fights per comparison by default. Both trinket orders are simulated; catalogs use the stable reference pair. Cached requests include race, talents, gear, engine, assignment, duration, and raid support. Returning to a prior setup reuses its results.

Useful HPS is effective healing plus shields actually consumed by damage. Overhealing and unused shields earn no score. Results meeting 99% assignment survival rank first; otherwise survival ranks before HPS. Hover for mana reserve, effective healing, absorbs, overhealing, and sampling margins. Small HPS differences are marked as ties. Native item effects and set bonuses apply; missing effects remain labelled.

The declared assignment has four recipients with 18,000 health. Group damage averages 800 total post-mitigation damage per second, tank damage focuses 700 per second on one recipient, and burst damage uses a documented twelve-second pulse pattern around the group workload. One-second damage rolls vary by Â±20%. Native highest available ranks and affordable lower-rank fallbacks follow Shield, Penance, Renew, Greater Heal, Flash Heal and Heal priorities with health-deficit thresholds. Native mana/item cooldown conditions apply. Baseline support includes intellect, stamina, spirit, Mark, Moonkin Aura, Kings, Wisdom, Mana Spring and Concentration; consumables are Distilled Wisdom, Nightfin Soup and Major Mana Potion. No Atiesh or external Innervate/Mana Tide is assumed. `scenario.json` in local data can explicitly override buffs and consumes.

This is GuildSim's own native assignment host, using the pinned WoWSims spell, talent, racial, mana and item mechanics. KFC's published assignment comparisons informed the assessment of the required metrics; no KFC code, service or account is embedded or required.

## Move an existing personal Ret setup

Choose the Ret character and **Move personal setup** in the helper. Select the old helper folder containing `config.json` and `output`. Settings, farming targets, reference trinkets, remembered pools, saved requests and fight history are copied locally. GuildSim validates its workflow before handoff and waits for the existing helper's active work to finish. Original helper files and SavedVariables remain available for rollback.

## Beta limits

In-game guild acceptance testing is required. Native item-effect coverage is incomplete; partial-model and statistical-error labels remain visible. Healing results describe a stationary assigned workload, not an entire 40-player raid. Movement, dispels, positioning and defensive utility against pre-mitigation damage are outside that assignment. The fixed casting policy is a reproducible comparison, not a claim of optimal play. GearMatic is a separate Ret prerequisite and is not bundled or modified. The Windows installer is not Authenticode signed; update metadata uses a separate Ed25519 release signature.

## Source and credits

The release archive includes GuildSim source and dependency notices. Native engine: [WoWSims Forever](https://github.com/wowsims/forever), pinned to v1.0.6, commit `d45287b64a140010800d631852ccc1f1a1bf91e2`, with an additive GuildSim initialization hook for friendly assignments. Existing native spell mechanics and Ret entry points are unchanged. Exporter: [WowSimsExporter](https://github.com/wowsims/exporter). Both retain their MIT notices. GuildSim-owned code is MIT licensed. GearMatic retains its own license.

Not affiliated with Blizzard, WoWSims or GearMatic.
# Engine release checks

GuildSim beta 5 includes WoWSims Forever v1.0.6. The helper checks the official upstream release metadata every six hours and shows whether the bundled engine is current. An unavailable check leaves simulations and signed GuildSim updates working. No character data is sent.

The repository also checks upstream daily and when its engine pin changes. A newer release opens or updates one maintenance issue; updating the bundled pin closes it. Engine changes are rebuilt and tested before they enter the signed GuildSim update channel. Guildmates do not need a compiler or a separate engine download.

Weapon results invalidated by a gear or talent change remain listed as saved results needing an update, with DPS withheld until they match the new capture. Explicitly requested and inspected weapons are included in comparisons even when absent from the default phase catalog; unsupported variants retain an error instead of an invented score.

## Hit and imported weights

Full fight comparisons include melee hit, misses and the cap. The login audit warning about linear item scores concerns imported GearMatic weights: those fixed weights do not recompute when another gear swap crosses a cap. Use the GuildSim full comparison for cap-sensitive choices and update weights after changing gear.

The native Ret regression test fixes every other input and checks 0%, 4%, 8% and 12% melee hit against a level-63 boss from behind. Over 1,000 fights, miss totals fall to zero at 8%; DPS at 8% and 12% is identical with the fixed seed. Run `go test -tags with_db ./ret -run TestNativeRetMeleeHit -v` from `engine`.
