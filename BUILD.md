# Maintainer release build

Guildmates use the installer. These tools are only needed to build a release.

Use Windows x64, Python 3.13, PyInstaller 6.22.3 and Go 1.27.4. The engine source is pinned to WoWSims Forever `a8bd7fd83a3a7c5102012ed87d86a71d175b3a89` (v1.0.4). Place its checkout at `engine/upstream`, and the official WowSimsExporter package at `bundle/addons/WowSimsExporter`. Keep their licenses. GuildSim adds a single host initialization hook; copy `engine/patches/guildsim_assignment.go` into `engine/upstream/sim/core`. No existing native spell or rotation implementation is replaced.

Build native executables from the `engine` directory:

```powershell
Copy-Item patches/guildsim_assignment.go upstream/sim/core/guildsim_assignment.go
go build -trimpath -buildvcs=false -ldflags="-s -w" -tags=with_db -o ../bundle/guildsim-engine.exe .
go build -trimpath -buildvcs=false -ldflags="-s -w" -tags=with_db -o ../bundle/ret-engine/retlocal.exe ./ret
go build -trimpath -buildvcs=false -ldflags="-s -w" -tags=with_db -o ../bundle/ret-engine/retbulk.exe ./bulk
```

Copy public upstream resources into `bundle/ret-engine/vendor/forever-master`: `assets/database`, `proto`, `ui/specs/paladin/retribution`, `ui/sim/constants`, and `sim/common/forever/stat_bonus_cds_auto_gen.go`. Copy the GuildSim addon templates into `bundle/ret-engine/addon`. Do not copy personal configuration, outputs, exports or account directories.

Generate `bundle/defaults.json` with `guildsim-engine.exe --prepare engine/upstream --defaults bundle/defaults.json`, run `prepare_bundle.py`, and copy `pipeline` to `bundle/pipeline`. Pipeline code remains editable source but its imports must also be included in the frozen helper so all standard-library binary dependencies are bundled.

The signing private key is stored only on the release maintainer's machine under the ignored `signing` directory. Never commit it, upload it, put it in a release asset, or reuse a key from another project. The public key is in `RELEASE-PUBLIC-KEY.txt` and is embedded in the launcher and setup executable using the Go linker variable `guildsim/beta/trust.PublicKey`.

Build `signrelease` into the ignored `signing` folder. Build `launcher` as a Windows GUI executable into `bundle/GuildSim Launcher.exe`, with that public key. Package `helper.py` using PyInstaller `--windowed --onedir --paths pipeline`, adding every pipeline module as a hidden import. Place the result at `packaged/GuildSim Helper`.

Run the automated tests and native smoke checks. `release.py` assembles the archive, creates the signed `update.json` and `update.json.sig`, and copies the authenticated payload into `engine/setup`. Build `setup` as a Windows GUI executable with the same public key to produce **GuildSim-Setup.exe**. The installer supports `--extract-to <folder>` for clean extraction tests without touching startup settings or the live game.

Before publishing, test the frozen helper with `--self-test --gui-smoke --report <file>`, run a frozen Ret task against a temporary game directory, verify signature rejection and corrupted-download recovery, and scan all release files for private data. Do not publish build caches, local fixture exports, signing material, or personal saved variables.

Publish these assets to the dedicated `bryan970/guildsim` repository:

- `GuildSim-Setup.exe`
- The versioned Windows archive named in `update.json`
- `update.json`
- `update.json.sig`

The release must be selected as the latest release so the stable `/releases/latest/download/` URLs resolve. Its title and version clearly identify the beta; do not hide the experimental Priest status. Bump the application/addon version for each published build; never silently replace an installed version with different bytes. Keep the preceding release available for recovery.

No other repositories, workflows or secrets are required for this distribution.

For tests, install Lupa into the maintainer Python environment (or point `GUILDSIM_QA_LIBS` at its installation), run `python -m unittest test_beta test_addon test_ret_browser test_updates test_ret_runtime test_healing`, and from `engine` run `go test -tags with_db ./healsim`. The native healing tests exercise consumed shields, real health deficits/deaths, no-casting controls and deterministic seeds. Helper integration tests run gear and trinket candidates across all three assignments, preserve separate fight records, and check cache reuse. These are beta-model checks; guild in-game acceptance and encounter calibration remain necessary.
