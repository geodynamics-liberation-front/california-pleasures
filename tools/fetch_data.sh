#!/usr/bin/env bash
# Download the source datasets into sources/ and verify them. Never installs anything.
#
#   GMTED2010 (USGS/NGA Global Multi-resolution Terrain Elevation Data), 30 arc-second mean
#       elevation tiles, public domain. Eleven 30° x 20° tiles cover the fifty states
#       (~17 MB each, ~190 MB in all). https://www.usgs.gov/coastal-changes-and-impacts/gmted2010
#   US Census Bureau cartographic boundary file cb_2023_us_state_500k (1:500,000 state
#       outlines), public domain, ~3 MB.
#
# Every download is checked against tools/SHA256SUMS before use; a file that fails is deleted and
# the build stops. Existing verified files are kept, so a rebuild does not download again.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/sources"
SUMS="$ROOT/tools/SHA256SUMS"
mkdir -p "$SRC"

die() { echo "fetch_data.sh: $*" >&2; exit 1; }

expected_sum() { awk -v f="$1" '$2 == f { print $1 }' "$SUMS"; }

# verify <file name>: compare with SHA256SUMS; delete the file and fail on mismatch
verify() {
  local name=$1 want have
  want=$(expected_sum "$name")
  [ -n "$want" ] || die "no checksum recorded for $name in tools/SHA256SUMS"
  have=$(sha256sum "$SRC/$name" | awk '{ print $1 }')
  if [ "$have" != "$want" ]; then
    rm -f "$SRC/$name"
    die "$name failed its SHA-256 check (got $have, expected $want); the file was deleted, re-run make to download it again"
  fi
}

# download <url> <destination>: retried, written to a temporary name first
download() {
  local url=$1 dest=$2
  echo "fetching  $url"
  if curl -fL --retry 3 --retry-delay 5 --connect-timeout 30 --progress-bar -o "$dest.part" "$url"; then
    mv "$dest.part" "$dest"
  else
    rm -f "$dest.part"; return 1
  fi
}

# fetch_verified <file name> <url>: keep an existing verified copy, else download and verify
fetch_verified() {
  local name=$1 url=$2
  if [ -s "$SRC/$name" ]; then
    verify "$name"; echo "have      $name (verified)"; return 0
  fi
  download "$url" "$SRC/$name" || die "could not download $name from $url; check the network and re-run make"
  verify "$name"
}

# --- GMTED2010 30 arc-second mean elevation tiles (named by their south-west corner) ---
GMTED=https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/topo/downloads/GMTED/Global_tiles_GMTED/300darcsec/mea
for tile in 30N150W 30N120W 30N090W 10N120W 10N090W 10N180W 50N180W 50N150W 70N180W 70N150W 50N150E; do
  dir="${tile:6:1}${tile:3:3}"            # 30N120W -> W120
  fetch_verified "${tile}_20101117_gmted_mea300.tif" "$GMTED/$dir/${tile}_20101117_gmted_mea300.tif"
done

# --- Census cartographic boundary file: states at 1:500,000 ---
CB=cb_2023_us_state_500k
fetch_verified "$CB.zip" "https://www2.census.gov/geo/tiger/GENZ2023/shp/$CB.zip"
if [ ! -s "$SRC/cb500k/$CB.shp" ] || [ ! -s "$SRC/cb500k/$CB.dbf" ]; then
  mkdir -p "$SRC/cb500k"
  unzip -oq "$SRC/$CB.zip" -d "$SRC/cb500k" || die "could not unpack $CB.zip (is unzip installed? is the file complete?)"
  echo "unpacked  $CB.zip -> cb500k/"
fi

echo "done: sources are in $SRC"
