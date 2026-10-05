"""Decode a Pokemon Gold/Silver battery save using the symbol table of the build
under test -- never a wiki memory map.

Everything here is derived at run time from two files produced by / shipped with the
disassembly you just built:

  upstream/poke<game>.sym        rgblink's symbol dump: sPlayerData, sCheckValue1, ...
  upstream/constants/charmap.asm the game's own text encoding
  upstream/constants/misc_constants.asm  SAVE_CHECK_VALUE_1 / _2

This is what lets the browser test say "the game was actually played" rather than
"the screenshots looked like gameplay". Gen 2's title screen runs a scripted attract
demo that is screenshot-identical to play; it cannot write a valid save containing a
player name you chose.
"""

import os
import re


class Symbols:
    def __init__(self, upstream, game="gold"):
        self.upstream = upstream
        self.sym = {}
        path = os.path.join(upstream, "poke%s.sym" % game)
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(";"):
                    continue
                parts = line.split()
                if len(parts) != 2 or ":" not in parts[0]:
                    continue
                bank, addr = parts[0].split(":")
                self.sym[parts[1]] = (int(bank, 16), int(addr, 16))
        if "sPlayerData" not in self.sym:
            raise RuntimeError("no sPlayerData in %s -- wrong or stale symbol file" % path)

        # the game's own character encoding
        self.charmap = {}
        with open(os.path.join(upstream, "constants", "charmap.asm")) as f:
            for line in f:
                m = re.match(r'\s*charmap\s+"(.*?)",\s*\$([0-9a-fA-F]+)', line)
                if m:
                    self.charmap.setdefault(int(m.group(2), 16), m.group(1))

        # the game's own "this save is real" markers (engine/menus/save.asm)
        self.consts = {}
        with open(os.path.join(upstream, "constants", "misc_constants.asm")) as f:
            for line in f:
                m = re.match(r"\s*DEF\s+(SAVE_CHECK_VALUE_[12])\s+EQU\s+(\d+)", line)
                if m:
                    self.consts[m.group(1)] = int(m.group(2))

    # ---- SRAM addressing -------------------------------------------------- #
    def srm_offset(self, name):
        """Byte offset of a symbol inside a flat 32 KiB .srm image."""
        bank, addr = self.sym[name]
        if not (0xA000 <= addr <= 0xBFFF):
            raise ValueError("%s at %02x:%04x is not in SRAM" % (name, bank, addr))
        return bank * 0x2000 + (addr - 0xA000)

    def field_offset(self, sram_base, wram_field, wram_base):
        """sPlayerData + (wPlayerName - wPlayerData), the way the game writes it."""
        return (self.srm_offset(sram_base)
                + self.sym[wram_field][1] - self.sym[wram_base][1])

    # ---- decoding --------------------------------------------------------- #
    def text(self, data, limit=16):
        out = ""
        for b in data[:limit]:
            if b == 0x50:          # "@", the string terminator
                break
            out += self.charmap.get(b, "?")
        return out

    def read_save(self, srm):
        """Return what the game itself would consider the state of this save."""
        if len(srm) != 32768:
            return {"error": "srm is %d bytes, expected 32768" % len(srm)}
        c1 = srm[self.srm_offset("sCheckValue1")]
        c2 = srm[self.srm_offset("sCheckValue2")]
        name_at = self.field_offset("sPlayerData", "wPlayerName", "wPlayerData")
        id_at = self.field_offset("sPlayerData", "wPlayerID", "wPlayerData")
        return {
            "check_value_1": c1,
            "check_value_2": c2,
            "check_values_ok": (c1 == self.consts["SAVE_CHECK_VALUE_1"]
                                and c2 == self.consts["SAVE_CHECK_VALUE_2"]),
            "expected_check_values": [self.consts["SAVE_CHECK_VALUE_1"],
                                      self.consts["SAVE_CHECK_VALUE_2"]],
            "player_name": self.text(srm[name_at:name_at + 12], 11),
            "player_name_bytes": " ".join("%02x" % b for b in srm[name_at:name_at + 8]),
            "player_id": (srm[id_at] << 8) | srm[id_at + 1],
            "offsets": {"sCheckValue1": self.srm_offset("sCheckValue1"),
                        "sCheckValue2": self.srm_offset("sCheckValue2"),
                        "player_name": name_at},
        }
