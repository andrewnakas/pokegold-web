#!/usr/bin/env python3
"""Headless browser check for the Pokemon Gold/Silver browser target.

Audio is off twice over: Chrome runs with --mute-audio and the page is loaded with
?mute=1, which sets EJS_volume to 0 and calls setVolume(0) once the core starts.

Three things this harness refuses to take on trust, each of them a real failure that
happened on this box:

1. THE TAB IS MINE. Ten agents share this machine. Chrome attaches to whatever is on
   a fixed debug port, so cdp.Chrome only ever uses an ephemeral one and reads the
   real port back from its own profile. On top of that the URL carries a nonce the
   attached target must echo, the core must identify as gambatte, and the sha1 the
   PAGE computes over the ROM must equal the sha1 of the file on disk.

2. THE SAVE IS REALLY ON DISK. gameManager.getSaveFile() calls saveSaveFiles() first,
   which writes the core's CURRENT SRAM over the file -- call it too early after a
   reload and it overwrites the restored save with blanks, which is exactly what an
   earlier version of this script did to itself. Persistence is therefore checked by
   reading emscripten's IDBFS IndexedDB store directly, on a fresh page load, BEFORE
   any ROM is picked and before a core exists to clobber it.

3. IT WAS PLAYED, NOT WATCHED. Gen 2's title screen runs an attract demo that is
   screenshot-identical to play. The gate is the game's own save: SAVE_CHECK_VALUE_1
   and _2 where engine/menus/save.asm puts them, and the player name we typed, read
   at sPlayerData + (wPlayerName - wPlayerData) using the .sym of this very build.

Usage: browsercheck.py [--rom PATH] [--game gold|silver] [--stage all|boot|play|save]
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cdp        # noqa: E402
import serve      # noqa: E402
import gen2save   # noqa: E402

OUT = os.path.join(HERE, "out")
UPSTREAM = os.path.normpath(os.path.join(HERE, "..", "upstream"))

# EmulatorJS / libretro joypad ids for the "gb" control scheme
A, B, SELECT, START, UP, DOWN, LEFT, RIGHT = 8, 0, 2, 3, 4, 5, 6, 7
NAMES = {A: "A", B: "B", SELECT: "SELECT", START: "START",
         UP: "UP", DOWN: "DOWN", LEFT: "LEFT", RIGHT: "RIGHT"}

# EmulatorJS pings this on localhost (emulator.js: `if (this.debug || localhost)`).
# The page's egress guard refuses it; that is the guard working, not a leak.
EXPECTED_REFUSALS = {"https://cdn.emulatorjs.org/stable/data/version.json"}

# Known-harmless 404s: EmulatorJS looks for an optional per-core "report" blob.
EXPECTED_404S = ("/data/cores/reports/",)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def banner(msg):
    print("\n=== %s" % msg, flush=True)


def attach(ch):
    ch.call("Runtime.enable")
    ch.call("Log.enable")
    ch.call("Page.enable")
    ch.call("Network.enable")


# ----------------------------------------------------------------- identity --

def assert_my_tab(ch, nonce):
    href = ch.eval("location.href")
    title = ch.eval("document.title")
    if nonce not in (href or ""):
        raise RuntimeError("attached to someone else's tab: %r (expected nonce %s)"
                           % (href, nonce))
    print("    tab identity ok: nonce echoed, title %r" % title)
    return {"href": href, "title": title}


def assert_core(ch, expect="gambatte"):
    core = ch.eval("window.EJS_emulator ? window.EJS_emulator.getCore() : null")
    system = ch.eval("window.EJS_emulator ? window.EJS_emulator.config.system : null")
    if core != expect:
        raise RuntimeError("wrong core: %r (expected %r) -- wrong page?" % (core, expect))
    print("    core: %s (EJS_core=%s)" % (core, system))
    return core


def assert_canvas(ch):
    dims = ch.eval("""(() => { const c = document.querySelector('#game canvas');
        if (!c) return null;
        const r = c.getBoundingClientRect();
        return {w: c.width, h: c.height, cssW: Math.round(r.width), cssH: Math.round(r.height)};
      })()""")
    if not dims or min(dims.values()) <= 0:
        raise RuntimeError("canvas has a zero dimension: %r" % dims)
    print("    canvas: %sx%s backing, %sx%s on screen" % (dims["w"], dims["h"], dims["cssW"], dims["cssH"]))
    return dims


# --------------------------------------------------------------------- page --

def load_rom_via_file_input(ch, url, rom_bytes_url):
    """Go through the page's real file-input change handler.

    A File is built in the page, put into the input's FileList through DataTransfer,
    and a change event dispatched: the same path a human click on the picker takes,
    minus the OS dialog. The file name is deliberately unhelpful -- the page must
    identify the ROM by its bytes, not by what it is called.
    """
    ch.call("Page.navigate", url=url)
    ch.pump(2.0)
    return ch.eval(
        """(async () => {
             const r = await fetch(%s);
             const buf = await r.arrayBuffer();
             const dt = new DataTransfer();
             dt.items.add(new File([buf], "my cartridge dump.gbc",
                                   {type: "application/octet-stream"}));
             const input = document.getElementById("file");
             input.files = dt.files;
             input.dispatchEvent(new Event("change", {bubbles: true}));
             return {bytes: buf.byteLength, files: input.files.length};
           })()""" % json.dumps(rom_bytes_url),
        await_promise=True, timeout=60)


def wait_started(ch, limit=90):
    end = time.time() + limit
    while time.time() < end:
        ch.pump(1.0)
        if ch.eval("!!(window.EJS_emulator && window.EJS_emulator.started)"):
            return True
    return False


def hold(ch, bid, seconds):
    """Hold a button across real running frames.

    Deliberately NOT window.__press(): that releases on a page setTimeout, and a
    timer that fires while Page.captureScreenshot has the page stalled can land the
    press and the release in the same batch, so the core polls neither. Pumping CDP
    events between the two edges keeps the page running across the hold.
    """
    ch.eval("window.EJS_emulator.gameManager.simulateInput(0,%d,1)" % bid)
    ch.pump(seconds)
    ch.eval("window.EJS_emulator.gameManager.simulateInput(0,%d,0)" % bid)
    ch.pump(0.08)


def press(ch, bid, dur=0.15):
    hold(ch, bid, dur)


def frame(ch):
    try:
        return ch.eval("window.EJS_emulator.gameManager.getFrameNum()")
    except Exception:
        return None


# ------------------------------------------------------------------- saves --

def idb_saves(ch):
    """Read emscripten's IDBFS store directly.

    Non-destructive, and it works with no core loaded at all -- which is the only
    honest way to see what actually survived a reload.

    The database is enumerated rather than guessed: this emscripten names the IDBFS
    database after the MOUNT POINT ("/data/saves"), not the old 'EM_FS_'+pathname.
    Guessing also has a nasty side effect -- indexedDB.open() on a name that does not
    exist CREATES it, so a wrong guess silently litters and then reports "empty".
    """
    return ch.eval(
        """(async () => {
             const dbs = await indexedDB.databases();
             const hit = dbs.find(d => String(d.name).indexOf('saves') !== -1);
             if (!hit) return {error: 'no saves database', databases: dbs};
             return await new Promise(resolve => {
               const req = indexedDB.open(hit.name);
               req.onerror = () => resolve({error: 'open failed', db: hit.name});
               req.onsuccess = () => {
                 const d = req.result;
                 const stores = Array.from(d.objectStoreNames);
                 const store = stores.includes('FILE_DATA') ? 'FILE_DATA' : stores[0];
                 if (!store) return resolve({error: 'no object store', db: hit.name});
                 const tx = d.transaction([store], 'readonly').objectStore(store);
                 const keys = tx.getAllKeys();
                 keys.onerror = () => resolve({error: 'getAllKeys failed', db: hit.name});
                 keys.onsuccess = () => {
                   const out = {db: hit.name, store: store,
                                keys: keys.result.map(String), files: {}};
                   let left = keys.result.length;
                   if (!left) return resolve(out);
                   keys.result.forEach(k => {
                     const g = tx.get(k);
                     const done = () => { if (--left === 0) resolve(out); };
                     g.onerror = done;
                     g.onsuccess = () => {
                       const v = g.result, c = v && v.contents;
                       if (c && (c.byteLength !== undefined || c.buffer)) {
                         const u = new Uint8Array(c.buffer ? c.buffer : c);
                         let s = '';
                         for (let i = 0; i < u.length; i++) s += String.fromCharCode(u[i]);
                         out.files[String(k)] = {len: u.length, b64: btoa(s)};
                       }
                       done();
                     };
                   });
                 };
               };
             });
           })()""", await_promise=True, timeout=30)


def pick_srm(idb):
    """The one 32 KiB battery save out of whatever IDBFS is holding."""
    if not idb or "files" not in idb:
        return None, None, idb
    for k, v in sorted(idb["files"].items()):
        if v["len"] == 32768:
            raw = base64.b64decode(v["b64"])
            return k, raw, idb
    return None, None, idb


def egress(ch):
    return ch.eval("window.__egress ? {blocked: window.__egress.blocked, bodies: window.__egress.bodies} : null")


def check_egress(ch):
    eg = egress(ch) or {"blocked": [], "bodies": []}
    unexpected = [b for b in eg["blocked"] if b["url"] not in EXPECTED_REFUSALS]
    return {"no_outbound_bodies": not eg["bodies"],
            "no_unexpected_refusals": not unexpected,
            "refused": sorted({b["url"] for b in eg["blocked"]}),
            "bodies": eg["bodies"]}


def http_failures(ch):
    out = set()
    for e in ch.events:
        if e.get("method") == "Network.responseReceived":
            r = e["params"]["response"]
            if r.get("status", 200) >= 400:
                out.add("%s %s" % (r["status"], r["url"]))
        elif e.get("method") == "Network.loadingFailed":
            if not e["params"].get("canceled"):
                out.add("failed %s" % e["params"].get("errorText"))
    return sorted(out)


def unexpected_http_failures(ch):
    return [f for f in http_failures(ch) if not any(p in f for p in EXPECTED_404S)]


def network_hosts(ch):
    """Every host the browser was actually asked to contact, from CDP, not the page."""
    hosts = set()
    for e in ch.events:
        if e.get("method") == "Network.requestWillBeSent":
            u = e["params"]["request"]["url"]
            if u.startswith("http"):
                hosts.add(u.split("/")[2])
    return sorted(hosts)


def shot(ch, name):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name + ".png")
    ch.screenshot(p)
    print("    shot -> test/out/%s.png" % name, flush=True)
    return p


def pixels_differ(p1, p2):
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    if not (os.path.exists(p1) and os.path.exists(p2)):
        return None
    a, b = Image.open(p1).convert("RGB"), Image.open(p2).convert("RGB")
    if a.size != b.size:
        return 1.0
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 12 else 0)
    return diff.histogram()[255] / float(a.size[0] * a.size[1])


def console_errors(ch):
    bad = []
    for lvl, t in ch.console():
        if lvl in ("error", "exception") or "Uncaught" in t:
            if "no-phone-home" in t or "cdn.emulatorjs.org" in t:
                continue
            if "404" in t:
                continue       # covered by unexpected_http_failures, with the URL
            bad.append((lvl, t[:200]))
    return bad


# -------------------------------------------------------------------- intro --

def run_intro(ch, mash_until=100.0, shots=None):
    """Title -> NEW GAME -> clock -> Oak -> naming -> the bedroom, by mashing A.

    The whole opening is A-advanceable, including the naming keyboard: mashing A
    spells AAAAAAA and lands on END, so the player ends up named AAAAAAA. That is
    the point -- it is a name we chose, and we read it back out of the save later.
    """
    shots = dict(shots or {})
    pending = sorted(shots)
    t0 = time.time()

    def elapsed():
        return time.time() - t0

    def advance_to(target):
        while pending and pending[0] <= target:
            s = pending.pop(0)
            ch.pump(max(0.0, s - elapsed()))
            shot(ch, shots[s])
        ch.pump(max(0.0, target - elapsed()))

    advance_to(8.0)
    press(ch, START)
    print("    t= 8.0s START", flush=True)
    while elapsed() < mash_until:
        press(ch, A)
        advance_to(min(mash_until, elapsed() + 0.35))
    for s in list(pending):
        advance_to(s)
    return elapsed()


# --------------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=None)
    ap.add_argument("--game", default="gold", choices=["gold", "silver"])
    ap.add_argument("--stage", default="all", choices=["all", "boot", "play", "save"])
    args = ap.parse_args()

    rom = args.rom or os.path.join(UPSTREAM, "poke%s.gbc" % args.game)
    if not os.path.exists(rom):
        sys.exit("no ROM at %s -- run ./build.sh first" % rom)
    rom_sha1 = hashlib.sha1(open(rom, "rb").read()).hexdigest()
    syms = gen2save.Symbols(UPSTREAM, args.game)

    print("ROM        %s" % rom)
    print("ROM sha1   %s  (on disk)" % rom_sha1)
    print("symbols    poke%s.sym: sPlayerData=%02x:%04x  name at .srm+0x%x"
          % (args.game, syms.sym["sPlayerData"][0], syms.sym["sPlayerData"][1],
             syms.field_offset("sPlayerData", "wPlayerName", "wPlayerData")))

    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)

    port = free_port()                      # one port for the whole run: IndexedDB
    srv = serve.start(port, rom_path=rom)   # is keyed by origin, port included
    nonce = uuid.uuid4().hex
    url = "http://127.0.0.1:%d/index.html?mute=1&hb&nonce=%s" % (port, nonce)
    romurl = "/_test/rom.gbc"
    R = {"rom": os.path.basename(rom), "rom_sha1_on_disk": rom_sha1, "nonce": nonce}

    ch = None
    try:
        ch = cdp.Chrome()
        print("devtools   ephemeral port %d, profile %s" % (ch.port, ch.profile))
        attach(ch)

        # ------------------------------------------------------------ boot --
        banner("boot: hand the ROM to the page's own file input")
        info = load_rom_via_file_input(ch, url, romurl)
        R["identity"] = assert_my_tab(ch, nonce)
        print("    input accepted %s bytes as 'my cartridge dump.gbc'" % info.get("bytes"))
        R["started"] = bool(wait_started(ch, 90))
        print("    core started: %s" % R["started"])
        if not R["started"]:
            shot(ch, "00-failed"); sys.exit("core never started")

        R["core"] = assert_core(ch, "gambatte")
        R["canvas"] = assert_canvas(ch)

        page_sha1 = ch.eval(
            "(document.getElementById('b-sha').innerText.match(/[0-9a-f]{40}/) || [null])[0]")
        R["rom_sha1_in_page"] = page_sha1
        R["rom_sha1_matches"] = (page_sha1 == rom_sha1)
        if not R["rom_sha1_matches"]:
            raise RuntimeError("page computed sha1 %s but the file on disk is %s"
                               % (page_sha1, rom_sha1))
        print("    page-computed ROM sha1 matches the file on disk")

        ch.pump(2.0); f0 = frame(ch)
        ch.pump(3.0); f1 = frame(ch)
        R["fps_approx"] = round((f1 - f0) / 3.0, 1) if (f0 and f1) else None
        R["frames_advance"] = bool(f0 and f1 and f1 > f0)
        print("    frames %s -> %s  (~%s fps)" % (f0, f1, R["fps_approx"]))
        R["muted"] = ch.eval("window.EJS_emulator.volume === 0 || window.EJS_volume === 0")
        print("    muted: %s" % R["muted"])
        R["save_file_path"] = ch.eval("window.EJS_emulator.gameManager.getSaveFilePath()")
        print("    core save path: %s" % R["save_file_path"])
        R["egress_boot"] = check_egress(ch)
        R["network_hosts"] = network_hosts(ch)
        print("    hosts contacted (per CDP): %s" % R["network_hosts"])
        if args.stage == "boot":
            print(json.dumps(R, indent=2)); return

        # ------------------------------------------------------------ play --
        banner("play: drive the opening")
        run_intro(ch, 100.0, shots={2.0: "01-gamefreak", 9.0: "02-title",
                                    11.0: "03-main-menu-new-game", 40.0: "04-prof-oak",
                                    99.0: "05-overworld"})
        before = shot(ch, "06-before-walk")
        hold(ch, DOWN, 0.7); ch.pump(0.4)
        hold(ch, LEFT, 0.7); ch.pump(0.6)
        after = shot(ch, "07-after-walk")
        R["walk_pixel_delta"] = pixels_differ(before, after)
        R["walked"] = bool(R["walk_pixel_delta"] and R["walk_pixel_delta"] > 0.01)
        print("    screen changed by %.1f%% after walking down+left"
              % (100 * (R["walk_pixel_delta"] or 0)))
        R["frames_after_intro"] = frame(ch)
        if args.stage == "play":
            print(json.dumps(R, indent=2)); return

        # ------------------------------------------------------------ save --
        banner("save: in-game SAVE")
        k0, srm0, _ = pick_srm(idb_saves(ch))
        print("    IDBFS before saving: %s %s" % (k0, len(srm0) if srm0 else None))

        press(ch, START); ch.pump(1.4); shot(ch, "08-start-menu")
        press(ch, DOWN); ch.pump(0.5)
        press(ch, DOWN); ch.pump(0.7); shot(ch, "09-cursor-on-save")
        press(ch, A);    ch.pump(1.6); shot(ch, "10-save-prompt-yes-no")
        press(ch, A)                                   # YES
        ch.pump(6.0)
        shot(ch, "11-saving")
        press(ch, A);    ch.pump(2.0); shot(ch, "12-saved")

        R["flush"] = ch.eval("window.__flushSave('test', true)", await_promise=True)
        ch.pump(2.5)
        key1, srm1, idb1 = pick_srm(idb_saves(ch))
        R["idb_db"] = idb1.get("db") if idb1 else None
        R["idb_files"] = ({k: v["len"] for k, v in idb1["files"].items()}
                          if idb1 and "files" in idb1 else None)
        R["srm_key"] = key1
        if srm1 is None:
            raise RuntimeError("no 32 KiB save in IDBFS after saving: %r" % idb1)
        R["srm_after_save"] = {"sha1": hashlib.sha1(srm1).hexdigest(), "len": len(srm1)}
        R["save_decoded"] = syms.read_save(srm1)
        print("    IDBFS after saving: %s sha1=%s" % (key1, R["srm_after_save"]["sha1"]))
        print("    decoded with this build's symbols: %s" % json.dumps(R["save_decoded"]))

        # ---------------------------------------------------------- reload --
        banner("reload: fresh page, NO rom picked -- read IDBFS before a core exists")
        nonce2 = uuid.uuid4().hex
        url2 = "http://127.0.0.1:%d/index.html?mute=1&hb&nonce=%s" % (port, nonce2)
        ch.call("Page.navigate", url="about:blank"); ch.pump(1.0)
        ch.call("Page.navigate", url=url2); ch.pump(2.5)
        assert_my_tab(ch, nonce2)
        key2, srm2, idb2 = pick_srm(idb_saves(ch))
        R["srm_after_reload"] = ({"sha1": hashlib.sha1(srm2).hexdigest(), "len": len(srm2)}
                                 if srm2 is not None else None)
        R["save_persisted"] = bool(srm2 is not None
                                   and hashlib.sha1(srm2).hexdigest() == R["srm_after_save"]["sha1"])
        R["idb_files_after_reload"] = ({k: v["len"] for k, v in idb2["files"].items()}
                                       if idb2 and "files" in idb2 else None)
        print("    IDBFS on a fresh load: db=%s files=%s"
              % (idb2.get("db") if idb2 else None, R["idb_files_after_reload"]))
        print("    picked %s -> %s" % (key2, R["srm_after_reload"]))
        print("    save persisted across reload: %s" % R["save_persisted"])
        R["save_decoded_after_reload"] = (syms.read_save(srm2) if srm2 is not None
                                         else {"check_values_ok": False, "player_name": None,
                                               "error": "no .srm in IDBFS after reload"})
        print("    decoded after reload: %s" % json.dumps(R["save_decoded_after_reload"]))

        # ground truth a human can see: CONTINUE, then the saved player back in the room
        banner("resume: load the ROM again and continue the saved game")
        load_rom_via_file_input(ch, url2, romurl)
        R["restarted"] = bool(wait_started(ch, 90))
        assert_core(ch, "gambatte")
        ch.pump(11.0)
        shot(ch, "13-title-after-reload")
        press(ch, START); ch.pump(4.0)
        menu2 = shot(ch, "14-main-menu-continue")
        R["main_menu_changed"] = pixels_differ(
            os.path.join(OUT, "03-main-menu-new-game.png"), menu2)
        print("    main menu differs from the first run by %.1f%%"
              % (100 * (R["main_menu_changed"] or 0)))
        press(ch, A); ch.pump(3.5); shot(ch, "15-save-status-panel")
        press(ch, A); ch.pump(3.0)
        press(ch, A); ch.pump(4.5); shot(ch, "16-resumed")

        R["egress_final"] = check_egress(ch)
        R["network_hosts"] = network_hosts(ch)
        R["console_errors"] = console_errors(ch)
        R["http_failures"] = http_failures(ch)
        R["unexpected_http_failures"] = unexpected_http_failures(ch)

        banner("summary")
        R["PASS"] = all([
            R["started"], R["restarted"], R["frames_advance"], R["muted"],
            R["rom_sha1_matches"], R["core"] == "gambatte", R["walked"],
            R["save_persisted"],
            R["save_decoded"]["check_values_ok"],
            R["save_decoded_after_reload"]["check_values_ok"],
            R["save_decoded"]["player_name"] == "AAAAAAA",
            R["save_decoded_after_reload"]["player_name"] == "AAAAAAA",
            R["egress_final"]["no_outbound_bodies"],
            R["egress_final"]["no_unexpected_refusals"],
            not R["unexpected_http_failures"], not R["console_errors"],
        ])
        print(json.dumps(R, indent=2))
        with open(os.path.join(OUT, "result-%s.json" % args.game), "w") as f:
            json.dump(R, f, indent=2)
        print("\nPASS" if R["PASS"] else "\nFAIL")
        sys.exit(0 if R["PASS"] else 1)

    finally:
        if ch:
            ch.kill()
        srv.shutdown()
        srv.server_close()
        print("server stopped, browser killed")


if __name__ == "__main__":
    main()
