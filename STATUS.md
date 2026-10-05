# pokegold — Pokémon Gold & Silver

**Status: byte-matching builds for both games, and a browser target that was driven
from the ROM picker to a saved game and back.** Everything below was run on this box
on 2026-10-05.

---

## 1. Upstream revision (pinned)

| | |
|---|---|
| Repo | https://github.com/pret/pokegold |
| Revision | `62388c7204e5d13aa05b4231e220b6760584d1b5` |
| Date / subject | 2026-09-29 — *Update some URLs, add a few constants (#152)* |
| Branch | `master`; this commit was the branch tip when pinned |
| Tags | the repo has none — the commit hash is the only pin available |

Pinned in `build.sh` as `PRET_REV`. `build.sh` checks that exact commit out, so a
re-run cannot silently drift onto a newer master.

## 2. Toolchain

| Tool | Version | Where it came from |
|---|---|---|
| rgbds | **1.0.4** (rgbasm / rgblink / rgbfix / rgbgfx) | prebuilt static Linux x86_64 release tarball |
| GNU make | 4.4.1 | system |
| gcc | 15.2.0 | system (builds `tools/` only) |
| OS | Ubuntu 26.04, x86_64, 12 cores | |

`rgbds-linux-x86_64.tar.xz` for v1.0.4, sha256
`3e19e50ea602e316be709160acaf0a708b1fa6d32d219ec541f244442895dbb7`,
installed to `~/decompfleet/shared/rgbds-1.0.4/bin`. The binaries are fully static
(`ldd` → "not a dynamic executable").

**Why not build rgbds from source, as pret's INSTALL.md says?** It cannot be done on
this machine: `bison` is not installed and `sudo` needs interactive auth, so neither
`apt-get install bison` nor `make install` is available. **And why not the distro
package?** `apt` offers rgbds **1.0.1**, which is *not* the version pret pins.

Getting the version right mattered, and the repo tells you two different things:

- `rgbdscheck.asm` only asserts a **minimum** — "pokegold requires rgbds v1.0.0 or
  newer". Passing that check does not imply a byte match; rgbgfx output and LZ
  settings do move between minor versions.
- `.github/workflows/main.yml` carries the real pin: `env: rgbds_version: v1.0.4`.
  That is what pret's own CI compares against, and that is what was used here.
  (`INSTALL.md` agrees — it says 1.0.4 — but CI is the authority.)

The recipe is written up for the other agents in `~/decompfleet/shared/rgbds-notes.md`.

## 3. Hashes — every target matches

`make compare` builds all six targets and checks them against upstream's `roms.sha1`.
All six pass, from a `git clean -xfd` tree, in 3.5 s on 12 cores:

| Target | sha1 | upstream `roms.sha1` |
|---|---|---|
| `pokegold.gbc` | `d8b8a3600a465308c9953dfa04f0081c05bdcb94` | ✅ match |
| `pokesilver.gbc` | `49b163f7e57702bc939d642a18f591de55d92dae` | ✅ match |
| `pokegold_debug.gbc` | `53783c57378122805c5b4859d19e1a224f02a1ed` | ✅ match |
| `pokesilver_debug.gbc` | `4c2fafebdbc7551f4cd3f348bdd17e420b93b6e7` | ✅ match |
| `pokegold.patch` (VC) | `b8253b915ade89c784c71adfdb11cf60bc1f7b59` | ✅ match |
| `pokesilver.patch` (VC) | `a38c0dec807e8a9e3626a0ec0fdf96bfb795ef3a` | ✅ match |

### Against the staged dumps — byte-for-byte, not just same-hash

| File | sha1 | md5 | size |
|---|---|---|---|
| `~/decompfleet/roms/pokegold.gbc` (staged) | `d8b8a3600a465308c9953dfa04f0081c05bdcb94` | `a6924ce1f9ad2228e1c6580779b23878` | 2097152 |
| `upstream/pokegold.gbc` (built) | `d8b8a3600a465308c9953dfa04f0081c05bdcb94` | `a6924ce1f9ad2228e1c6580779b23878` | 2097152 |
| `~/decompfleet/roms/pokesilver.gbc` (staged) | `49b163f7e57702bc939d642a18f591de55d92dae` | `2ac166169354e84d0e2d7cf4cb40b312` | 2097152 |
| `upstream/pokesilver.gbc` (built) | `49b163f7e57702bc939d642a18f591de55d92dae` | `2ac166169354e84d0e2d7cf4cb40b312` | 2097152 |

`cmp` reports both pairs identical.

### The revision question, answered

The brief flagged the staged dumps as "(USA, Europe) (SGB Enhanced) (GB Compatible),
no Rev marker, so probably rev 0 — verify before concluding". **Verified, no mismatch
to report.** Upstream builds exactly one Gold ROM and one Silver ROM (plus debug and
Virtual Console variants), documents their sha1s in `README.md` and `roms.sha1`, and
both staged files match those documented hashes exactly. There is no rev-0/rev-1 split
in this disassembly to get wrong — pret/pokegold has a single revision target per game,
and these dumps are it.

## 4. Browser target

`web/` is a static site. Serve it from anywhere (GitHub Pages works; no server-side
anything).

- **Core:** libretro **gambatte**, via **EmulatorJS 4.2.3**, both vendored under
  `web/data/` (licences and sources in `web/THIRD_PARTY.md`). No emscripten build was
  needed — the core is a GPL-2.0 wasm build published by the EmulatorJS project, and
  that is the fleet's established pattern (`/mnt/d/n64work/padroll`).
- **The user supplies the ROM.** File picker or drag-and-drop → `file.arrayBuffer()` →
  SHA-1 via WebCrypto → handed to the core as an in-memory `File`. Gold, Silver and
  both debug builds are recognised by hash and named in the status bar; any other 2 MiB
  GBC ROM still loads, labelled as unrecognised.
- **It is never uploaded.** Two independent layers:
  - a CSP `<meta>` pinning `connect-src 'self' blob: data:`, so the *browser* refuses
    any cross-origin request;
  - `web/no-phone-home.js`, loaded before everything else, which wraps `fetch`,
    `XMLHttpRequest`, `sendBeacon`, `WebSocket` and `RTCPeerConnection`, refuses
    anything not same-origin, and records every outbound body it sees.
  In the test, CDP's own network log shows the browser contacted exactly one host —
  `127.0.0.1:<test port>`, the local static server — and zero requests carried a body.
- **Saves persist.** `EJS_gameName` is set per game, so the core always writes
  `/data/saves/Gambatte/pokegold.srm` (or `pokesilver.srm`) on emscripten's IDBFS
  mount, which is backed by IndexedDB. The page also flushes explicitly every 10 s and
  on `visibilitychange`, because IDBFS's `autoPersist` debounces and a tab left alone
  mid-debounce loses the write. `pokegold.rtc` (the real-time clock) persists alongside
  it.

  **Stock EmulatorJS 4.2.3 destroys the battery save every time you leave the page, and
  this page patches around it.** `emulator.js:1092` registers a `beforeunload` listener
  that fires its `exit` event; the handler in `GameManager.js:44` ends with
  `FS.unmount("/data/saves")`, and the IndexedDB store backing that mount comes back
  **empty**. Measured, with no gameplay needed — the core writes a `.srm` at boot:

  ```
  boot, wait, read IndexedDB    -> {pokegold.srm: 32768, pokegold.rtc: 8}
  navigate away, come back      -> {}                      <- gone
  same again, that one listener suppressed:
  navigate away, come back      -> {pokegold.srm: 32768, pokegold.rtc: 8}
  ```

  So `index.html` wraps `window.addEventListener` before injecting `data/loader.js`,
  drops EmulatorJS's `beforeunload`, and registers its own, which writes and syncs and
  never unmounts. Every flush is additionally guarded by a check that `/data/saves` is
  still an IDBFS mount with `autoPersist`, because syncing a non-mount makes IDBFS's
  reconcile delete the remote entries.

  It is timing-sensitive — whether the teardown beats the page dying — so it *passes*
  sometimes: I had two green runs before three reds from identical code, and wasted a
  cycle blaming my own unload handler before running the controlled experiment above.
  The regression check is the test's "read IndexedDB on a fresh load with **no ROM
  picked**" step; the symptom is an empty store, not a changed hash. Written up for the
  fleet as trap 10 in `~/decompfleet/shared/emulatorjs-notes.md` — every agent shipping a
  battery-backed title (pokecrystal, pokefirered, zelda1, …) has this bug today.
- `EJS_disableDatabases = true` and `EJS_CacheLimit = 0` keep the ROM itself out of
  IndexedDB. It exists only in page memory, for the life of the tab.

## 5. What was actually tested

`test/browsercheck.py` — headless Chrome 151 over a hand-rolled CDP client (no pip on
this box, so no playwright/selenium). **Audio off twice: Chrome runs `--mute-audio`
and the page runs `?mute=1` → `EJS_volume = 0`.** Run: `python3 test/browsercheck.py
--game gold|silver`. Both PASS.

Screenshots land in `test/out/` (gitignored). I looked at every one of them.

Last full run, 2026-10-05, after the save-persistence fix in §4:

| | Gold | Silver |
|---|---|---|
| result | **PASS** | **PASS** |
| `.srm` sha1, after save → after reload | `7f505d1f…` → `7f505d1f…` | identical pair |
| decoded save, before → after reload | `AAAAAAA` / id 33522 / check 99,127 | `AAAAAAA` / id 20118 / check 99,127 |
| IndexedDB on the fresh load | `pokegold.srm` 32768, `pokegold.rtc` 8 | `pokesilver.srm` 32768, `pokesilver.rtc` 8 |

### Proving the tab is mine

Ten agents share this machine and a fixed DevTools port lets Chrome attach to someone
else's browser — `/json/list` then hands you their page and you grade their game as
yours. So:

- `--remote-debugging-port=0`, with the real port read back from `DevToolsActivePort`
  inside this harness's own private `--user-data-dir`. There is no port argument.
- a nonce in the URL that the attached target must echo back from `location.href`;
- `EJS_emulator.getCore()` must be `gambatte`;
- the SHA-1 **the page computed over the ROM bytes** must equal the SHA-1 of the file
  on disk.

All four assert on every run. The earlier results in this file were re-run from scratch
under these checks.

### Verified for both Gold and Silver

| Check | Gold | Silver |
|---|---|---|
| ROM accepted through the page's real `<input type=file>` handler (DataTransfer + `change`), under a deliberately unhelpful filename | ✅ | ✅ |
| Page-computed sha1 == on-disk sha1 | `d8b8a36…` | `49b163f…` |
| Core identity | gambatte | gambatte |
| Canvas has non-zero size (960×686 backing and on screen) | ✅ | ✅ |
| Runs at ~60 fps, frame counter climbing | ✅ | ✅ |
| Muted | ✅ | ✅ |
| Hosts contacted, per CDP network log | `127.0.0.1:<port>` only | same |
| Outbound request bodies | none | none |
| Played: title → NEW GAME → clock → Prof. Oak → naming → bedroom in New Bark Town | ✅ | ✅ |
| Walked: D-pad moves the player (36.5% of pixels change) | ✅ | ✅ |
| In-game START → SAVE → YES completes | ✅ | ✅ |
| Save survives a full page reload (`.srm` sha1 identical before and after) | ✅ | ✅ |
| …and resumes: CONTINUE on the main menu, status panel, player back where we saved | ✅ | ✅ |
| Console errors | none | none |
| Unexpected HTTP failures | none | none |

### "Played", not "watched"

Gen 2's title screen runs a scripted attract demo that is screenshot-identical to
playing, so screenshots alone settle nothing. The gate is the game's own save data,
decoded with the symbol table **of the build under test** (`test/gen2save.py` parses
`upstream/poke<game>.sym`, `constants/charmap.asm` and `constants/misc_constants.asm`
at run time; nothing is hardcoded from a wiki):

```
sCheckValue1 = 01:a008 -> .srm+0x2008 = 99   (SAVE_CHECK_VALUE_1, engine/menus/save.asm)
sCheckValue2 = 01:ad6b -> .srm+0x2d6b = 127  (SAVE_CHECK_VALUE_2)
player name  = sPlayerData + (wPlayerName - wPlayerData) -> .srm+0x200b
             = 80 80 80 80 80 80 80 50 -> "AAAAAAA"   (charmap.asm: "A"=$80, "@"=$50)
```

Both check values are what `save.asm` tests for, and the player name is the one the
harness typed by mashing A through the naming keyboard. An attract demo cannot produce
either. Both decode identically **before** the reload and **after** it, for both games.

The `.srm` sha1 itself is not reproducible across runs — Gen 2 rolls a random trainer
ID at new game, and the save carries the clock — so the assertion is that the hash is
*the same on both sides of the reload within a run*, not that it equals some fixed
value. The decoded player name and check values are the stable part, and they are what
the pass/fail gate uses. `test/out/result-<game>.json` has that run's actual numbers.

### How persistence was measured (and how it was measured wrong first)

`gameManager.getSaveFile()` calls `saveSaveFiles()` first, which writes the core's
*current* SRAM over the save file. Calling it a second after a reload — before the core
has loaded the restored `.srm` — overwrites a good save with blanks and then reports it
blank. My first harness did exactly that and produced one green run and one red run
from the same code. Persistence is now read **straight out of IndexedDB on a fresh page
load with no ROM picked**, so no core exists to clobber anything. The IDBFS database is
enumerated with `indexedDB.databases()`, never guessed — `indexedDB.open()` *creates* a
database that does not exist, so a wrong guess invents an empty one and reports "lost".

## 6. What was NOT tested — read this before trusting anything above

- **Only the opening ~2 minutes of each game was played.** The harness reaches the
  bedroom in New Bark Town, walks two tiles, and saves. It has never left the house.
  Nothing downstream — getting a starter, battles, the Pokédex, Pokégear, gyms, Kanto,
  link/trade, Mystery Gift, the Game Corner, credits — has been exercised at all.
- **No audio was ever enabled,** so audio output is completely unverified in the
  browser. The fleet rules require muting; that means "sound works" is not a claim I
  can make.
- **Real-time-clock behaviour over time is unverified.** `pokesilver.rtc` /
  `pokegold.rtc` persist (8 bytes, confirmed in IndexedDB), and the main menu shows a
  live clock after reload, but I did not test day/night rollover, the Bug-Catching
  Contest, Lottery, or anything else that depends on the clock advancing across
  sessions or on gambatte's RTC drifting from real time.
- **Only headless Chrome 151 on Linux was used.** No Firefox, no Safari, no iOS, no
  Android, no touch controls tested. EmulatorJS's on-screen gamepad is configured but
  was never pressed.
- **The OS file dialog was not driven.** The test injects a `File` into the real
  `<input type=file>` via `DataTransfer` and dispatches a real `change` event, so the
  page's own handler runs end to end — but the native picker UI itself is untested.
  Drag-and-drop is wired to the same entry point and was likewise not driven.
- **GitHub Pages deployment is untested.** The site was only ever served from
  `http://127.0.0.1` by `test/serve.py`. Note one behavioural difference: EmulatorJS
  4.2.3 only pings `cdn.emulatorjs.org` when the host is localhost
  (`src/emulator.js:207`), so the egress guard logs one refused request in the test
  that would not occur in production.
- **The debug ROMs and the Virtual Console patches build and match, but were never
  run.** Only `pokegold.gbc` and `pokesilver.gbc` were booted.
- **Save-state (as opposed to battery-save) persistence is untested.** EmulatorJS's
  own quick-save/load-state UI exists; I did not exercise it.
- **`make DEBUG=1` was not used.** pret's CI compares with `DEBUG=1` (which only adds
  `-E` to rgbasm, exporting more symbols); I compared a plain `make`. All six hashes
  match either way by construction, but I did not run the `DEBUG=1` path.
- **One known-harmless 404 remains:** `data/cores/reports/gambatte.json`. EmulatorJS
  looks for an optional per-core "report" blob that the CDN does not ship for this
  version. It is whitelisted in the test, not fixed.

## 7. Gen2Recomped — evaluated, not used

Upstream-adjacent project: **https://github.com/UNDERdecoded/Gen2Recomped** (352 stars,
Lua, v0.8.5, very actively developed — released the day this was written).

**Conclusion: the emulator core is the right call here, and it is not close.**

- **It is not a recompilation.** Despite the name, it is a hand-written **reimplementation
  in Lua on LÖVE2D** — its own engine, its own script VM, its own map behaviour. It
  reads a user ROM to extract data and graphics, then runs its own code. It never runs
  the ROM we built, so it cannot demonstrate anything about a byte-matching build. Our
  whole deliverable is *this ROM, in a browser*; Gen2Recomped structurally cannot do it.
- **There is no web target.** `ports/` contains `switch` and `uwp`. No wasm, no love.js,
  no browser build of any kind. Getting one would mean porting LÖVE2D to wasm ourselves —
  far more work than vendoring a 967 KB gambatte core, for a worse result.
- **Fidelity is approximate by construction.** `docs/` is full of "parity" documents
  (`gen2-encounter-rate-parity.md`, `gen2-daycare-parity.md`, `gen2-friendship-parity.md`,
  `gameboy-hardware-limitations.md`, …) — i.e. a catalogue of the places where behaviour
  is still being matched to the original. gambatte running the matching ROM has no such
  gap.
- Licence is `NOASSERTION` on GitHub, which is its own reason for caution.

It looks like a good project for native/handheld play. It is the wrong tool for this job.

## 8. Layout

```
build.sh              fetch rgbds 1.0.4, clone+pin pret/pokegold, build, verify hashes
upstream/             the disassembly (cloned by build.sh, gitignored, never vendored)
web/                  the browser target — static, deployable as-is
  index.html          ROM picker, emulator host, save flushing, test hooks
  no-phone-home.js    runtime egress guard (loaded first)
  data/               EmulatorJS 4.2.3 + gambatte core (vendored, GPL — see THIRD_PARTY.md)
test/
  browsercheck.py     the headless check described above
  cdp.py              minimal CDP client (hand-rolled websocket; no pip on this box)
  serve.py            threaded static server + one test-only route for the ROM
  gen2save.py         decodes a .srm using the built ROM's own .sym and charmap
  out/                screenshots and result JSON (gitignored)
```

No ROM, and nothing extracted from one, is in this directory or in `web/`. `.gitignore`
excludes every ROM extension (including `*.md` for Genesis, with `STATUS.md` and
`THIRD_PARTY.md` negated), `*.srm`, `*.sav`, `upstream/` and `test/out/`.

## 9. Proposed catalog fragment

Not merged — `src/data/games.json` is the user's to edit. Field names follow
`~/decompfleet/shared/catalog-schema.md` (the real 41-record schema), not my guesses.

One record covers both games: the page identifies Gold or Silver from the ROM's SHA-1
and names it on screen, so a single entry serves both. Splitting it into
`pokemon-gold` / `pokemon-silver` pointing at the same `embedUrl` would work too.

Three values I could not read off anything and had to pick — please check them:
`shelf` (I used `"decomp"`; the only example I had was `"cleanroom"`, which this is not),
`embedUrl` (depends where you host `web/`), and `complete` (see the note below the JSON).

```json
{
  "id": "pokemon-gold-silver",
  "title": "Pokémon Gold & Silver",
  "aliases": [
    "pokegold",
    "pokesilver",
    "Pokemon Gold",
    "Pokemon Silver",
    "Pokémon Gold and Silver"
  ],
  "year": 1999,
  "genre": "RPG",
  "kind": "Disassembly",
  "mode": "files",
  "engine": "The real ROM, built byte-for-byte from the pret/pokegold disassembly, running on the libretro Gambatte core (EmulatorJS 4.2.3, WebAssembly)",
  "description": "Johto, Kanto, day and night, and 100 new Pokémon.",
  "overview": "Pokémon Gold and Silver built from the pret/pokegold disassembly with rgbds 1.0.4, byte-identical to the retail cartridges, running in the browser on a WebAssembly Game Boy Color core. You supply your own ROM: it is read with FileReader, kept in the tab's memory and never uploaded, and the page recognises Gold or Silver by its SHA-1. Battery saves persist in this browser.",
  "source": "https://github.com/pret/pokegold",
  "engineLicense": "EmulatorJS is GPL-3.0 and the Gambatte core is GPL-2.0; the pret/pokegold disassembly is unlicensed research. See web/THIRD_PARTY.md.",
  "assetLicense": "No game data is distributed. Everything comes from the ROM you load.",
  "assetRequirements": "You supply your own Pokémon Gold or Silver ROM (2,097,152 bytes). It is read in the browser and never uploaded. Gold sha1 d8b8a3600a465308c9953dfa04f0081c05bdcb94, Silver sha1 49b163f7e57702bc939d642a18f591de55d92dae — the same ROMs this project's build produces.",
  "controls": [
    "Arrow keys — D-pad",
    "X — A",
    "Z — B",
    "Enter — Start",
    "Shift — Select",
    "Gamepad — standard mapping",
    "Touch — on-screen Game Boy pad on phones and tablets"
  ],
  "saveInstructions": "Save in game the normal way (START → SAVE). The battery save is kept in this browser's storage, per game, and survives a reload. Clearing site data removes it.",
  "limitations": [
    "Only the opening was play-tested — up to the bedroom in New Bark Town, an in-game save, a reload and a resume. Nothing after that has been exercised.",
    "Audio is unverified: every test ran muted.",
    "Only tested in headless Chrome on Linux. Firefox, Safari, iOS, Android and the on-screen controls are untested.",
    "Real-time-clock behaviour over days — day/night, the Bug-Catching Contest, the lottery — is untested.",
    "Link trading and battling are not possible in a single browser tab."
  ],
  "inputs": [
    "Gamepad",
    "Keyboard",
    "Touch"
  ],
  "downloadMB": null,
  "complete": true,
  "color": "#d4a23a",
  "shelf": "decomp",
  "platform": "Game Boy Color",
  "launch": "embed",
  "touch": true,
  "embedUrl": "https://andrewnakas.github.io/pokegold/",
  "verification": {
    "status": "smoke-tested",
    "date": "2026-10-05",
    "browsers": ["Chrome 151 (headless, Linux)"],
    "scope": "Both ROMs build byte-identical to the retail cartridges (sha1 verified against pret's roms.sha1 and against the staged dumps). In the browser: loaded through the page's own file picker, ran at 60 fps, played the opening through to the bedroom in New Bark Town, walked, saved in game, reloaded the page and resumed from the save — the restored save decodes with the game's own SAVE_CHECK_VALUE_1/2 and the player name that was typed, read using the symbol table of the build under test. Nothing past the first house was played; audio was muted throughout.",
    "playthrough": false
  }
}
```

On `complete`: set to `true` because the ROM is byte-identical to the retail cartridge —
the *game* is complete by construction, there is no porting work left undone. What is
partial is my **testing**, which is why `verification.playthrough` is `false` and the
caveats are in `limitations`. If `complete` means "somebody finished it in this
runtime", set it to `false` — I did not.
