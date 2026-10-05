#!/usr/bin/env bash
# Build Pokemon Gold and Silver from pret/pokegold and check the ROMs byte-match.
#
# Nothing here needs root. rgbds comes from the upstream project's own statically
# linked Linux release, because this machine has no bison and no sudo, so building
# rgbds from source (what pret's INSTALL.md tells you to do) cannot work here.
#
# Usage: ./build.sh            build everything and verify
#        ./build.sh clean      remove the clone and the toolchain
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED="$HOME/decompfleet/shared"

# Pinned upstream revision. pret/pokegold has no tags; this is the master commit
# the ROMs in this repo were verified against.
PRET_REV=62388c7204e5d13aa05b4231e220b6760584d1b5
# The version pret's own CI pins (.github/workflows/main.yml: rgbds_version).
# rgbdscheck.asm only demands ">= 1.0.0", which is NOT enough to byte-match.
RGBDS_VER=v1.0.4
RGBDS_TARBALL_SHA256=3e19e50ea602e316be709160acaf0a708b1fa6d32d219ec541f244442895dbb7

RGBDS_DIR="$SHARED/rgbds-${RGBDS_VER#v}"

if [ "${1:-}" = "clean" ]; then
  rm -rf "$HERE/upstream" "$RGBDS_DIR"
  echo "cleaned"
  exit 0
fi

# ---------------------------------------------------------------- toolchain --
if [ ! -x "$RGBDS_DIR/bin/rgbasm" ]; then
  echo ">> installing rgbds $RGBDS_VER into $RGBDS_DIR"
  mkdir -p "$SHARED/dl" "$RGBDS_DIR/bin"
  tarball="$SHARED/dl/rgbds-$RGBDS_VER-linux-x86_64.tar.xz"
  if [ ! -f "$tarball" ]; then
    curl -fsSL -o "$tarball" \
      "https://github.com/gbdev/rgbds/releases/download/$RGBDS_VER/rgbds-linux-x86_64.tar.xz"
  fi
  echo "$RGBDS_TARBALL_SHA256  $tarball" | sha256sum -c -
  tmp=$(mktemp -d)
  tar xJf "$tarball" -C "$tmp"
  install -m755 "$tmp"/rgbasm "$tmp"/rgblink "$tmp"/rgbfix "$tmp"/rgbgfx "$RGBDS_DIR/bin/"
  rm -rf "$tmp"
fi
export PATH="$RGBDS_DIR/bin:$PATH"
echo ">> rgbasm $(rgbasm --version)"

# ----------------------------------------------------------------- sources --
if [ ! -d "$HERE/upstream/.git" ]; then
  echo ">> cloning pret/pokegold"
  git clone --quiet https://github.com/pret/pokegold.git "$HERE/upstream"
fi
cd "$HERE/upstream"
git fetch --quiet origin
git checkout --quiet "$PRET_REV"
echo ">> pret/pokegold at $(git rev-parse HEAD)"

# ------------------------------------------------------------------- build --
make -j"$(nproc)" compare

echo
echo ">> built ROMs"
sha1sum pokegold.gbc pokesilver.gbc pokegold_debug.gbc pokesilver_debug.gbc

staged="$HOME/decompfleet/roms"
if [ -f "$staged/pokegold.gbc" ]; then
  echo
  echo ">> byte-for-byte against the staged dumps"
  cmp "$staged/pokegold.gbc"   pokegold.gbc   && echo "   gold:   identical"
  cmp "$staged/pokesilver.gbc" pokesilver.gbc && echo "   silver: identical"
fi
