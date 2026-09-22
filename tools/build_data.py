#!/usr/bin/env python3
"""Convert the downloaded sources into site/data/: one elevation grid per state.

    python3 tools/build_data.py            # all fifty states
    python3 tools/build_data.py CA NV      # only these (for development)

Inputs (fetched by tools/fetch_data.sh into sources/):
    *_gmted_mea300.tif        GMTED2010 30 arc-second mean elevation, one 30 x 20 degree tile
                              each, uncompressed 16-bit GeoTIFF, nodata -32768, metres.
    cb500k/cb_2023_us_state_500k.shp
                              Census cartographic state boundaries at 1:500,000.

Outputs:
    site/data/states.json     the list of states and the facts the site needs
    site/data/<xx>.bin        the state's grid, "PLSR" format (see write_grid below)
    site/data/map.bin         the national map for the front page, "PLSM" format (see build_map)
    site/data/outlines.json   the state outlines on that map, as SVG path strings

Each state's grid is the 30 arc-second mosaic cropped to the state's bounding box, block
averaged so it is at most MAX_COLS columns wide, and masked with the state polygon: every cell
outside the state is NODATA. Sea and lake cells inside the outline keep their GMTED value.
Longitudes east of the antimeridian (the western Aleutians) are shifted by -360 so Alaska is
one continuous grid. Hawaii is clipped to its eight main islands.

Only numpy and pyshp are needed: the GeoTIFF reader below handles exactly the uncompressed,
single-band, strip-organised files GMTED ships and refuses anything else. Any problem stops the
build with a message on stderr and a non-zero exit status.
"""

import json
import os
import struct
import sys

import numpy as np

try:
    import shapefile
except ImportError:
    sys.exit("build_data.py: the Python package pyshp is missing: pip install -r tools/requirements.txt")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "sources")
OUT = os.path.join(ROOT, "site", "data")

RES = 120                 # GMTED cells per degree (30 arc-seconds)
TILE_W, TILE_H = 30, 20   # degrees covered by one GMTED tile
NODATA = -32768
MAX_COLS = 1200           # widest grid shipped; wider states are block averaged
DATA_VERSION = 1

TILES = ["30N150W", "30N120W", "30N090W", "10N120W", "10N090W", "10N180W",
         "50N180W", "50N150W", "70N180W", "70N150W", "50N150E"]

# The fifty states by postal abbreviation, with optional clipping boxes (west, east, south, north).
STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY",
}
CLIP = {
    "HI": (-161.0, -154.0, 18.0, 23.0),   # the main islands, not the Northwestern chain
}


def die(msg):
    sys.exit(f"build_data.py: {msg}")


# --- a minimal GeoTIFF reader for the GMTED tiles -------------------------------------------

_TYPES = {1: ("B", 1), 2: ("c", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8), 11: ("f", 4), 12: ("d", 8)}


def read_gmted(path):
    """Return (array[int16, rows x cols], west edge, north edge, cell size) of one tile."""
    with open(path, "rb") as f:
        data = f.read()
    order = {b"II": "<", b"MM": ">"}.get(data[:2])
    if order is None or struct.unpack(order + "H", data[2:4])[0] != 42:
        die(f"{path} is not a classic TIFF file")
    ifd = struct.unpack(order + "I", data[4:8])[0]
    count = struct.unpack(order + "H", data[ifd:ifd + 2])[0]
    tags = {}
    for i in range(count):
        tag, typ, n, val = struct.unpack(order + "HHI4s", data[ifd + 2 + 12 * i:ifd + 14 + 12 * i])
        if typ not in _TYPES:
            continue
        fmt, size = _TYPES[typ]
        if n * size <= 4:
            raw = val[:n * size]
        else:
            off = struct.unpack(order + "I", val)[0]
            raw = data[off:off + n * size]
        tags[tag] = raw.decode("latin1") if typ == 2 else struct.unpack(order + fmt * n, raw)

    def one(tag, default=None):
        v = tags.get(tag)
        return default if v is None else v[0]

    width, height = one(256), one(257)
    if (one(258) != 16 or one(259, 1) != 1 or one(277, 1) != 1 or one(339, 1) != 2
            or one(284, 1) != 1 or 273 not in tags or 279 not in tags):
        die(f"{path}: expected an uncompressed, single-band, signed 16-bit, strip-organised GeoTIFF")
    if 33550 not in tags or 33922 not in tags:
        die(f"{path}: missing the GeoTIFF pixel scale or tie point tags")
    dx, dy = tags[33550][0], tags[33550][1]
    if abs(dx - 1 / RES) > 1e-9 or abs(dy - 1 / RES) > 1e-9:
        die(f"{path}: expected 30 arc-second cells, found {dx} x {dy} degrees")
    west, north = tags[33922][3], tags[33922][4]
    nodata = int(tags[42113].strip("\0 ")) if 42113 in tags else NODATA
    if nodata != NODATA:
        die(f"{path}: expected nodata {NODATA}, found {nodata}")

    rows_per_strip = one(278, height)
    offsets, counts = tags[273], tags[279]
    arr = np.empty((height, width), dtype=np.int16)
    for s, (off, cnt) in enumerate(zip(offsets, counts)):
        r0 = s * rows_per_strip
        rows = min(rows_per_strip, height - r0)
        if cnt != rows * width * 2 or off + cnt > len(data):
            die(f"{path}: strip {s} is truncated; delete the file and re-run make")
        arr[r0:r0 + rows] = np.frombuffer(data, dtype=order + "i2", count=rows * width, offset=off).reshape(rows, width)
    return arr, west, north, dx


class Mosaic:
    """The GMTED tiles as one virtual grid in 'working' longitude (east of 180 shifted by -360).

    Global cell indices: column c covers longitude [-180 + c/RES, -180 + (c+1)/RES), which is
    negative for the western Aleutians; row r covers latitude (90 - (r+1)/RES, 90 - r/RES].
    """

    def __init__(self):
        self.tiles = {}
        for name in TILES:
            path = os.path.join(SRC, f"{name}_20101117_gmted_mea300.tif")
            if not os.path.exists(path):
                die(f"missing {path}; run make fetch")
            lat_sw = int(name[:2]) * (1 if name[2] == "N" else -1)
            lon_sw = int(name[3:6]) * (1 if name[6] == "E" else -1)
            if lon_sw >= 0:
                lon_sw -= 360
            self.tiles[name] = (path, lon_sw, lat_sw)
        self.cache = {}

    def load(self, name):
        if name not in self.cache:
            path, lon_sw, lat_sw = self.tiles[name]
            arr, west, north, _ = read_gmted(path)
            if west >= 0:
                west -= 360
            if abs(west - lon_sw) > 0.01 or abs(north - (lat_sw + TILE_H)) > 0.01 or arr.shape != (TILE_H * RES, TILE_W * RES):
                die(f"{path}: georeferencing does not match its name ({west}, {north}, {arr.shape})")
            print(f"  read {os.path.basename(path)}")
            self.cache[name] = arr
        return self.cache[name]

    def window(self, c0, c1, r0, r1):
        """Cells [r0, r1) x [c0, c1) of the global grid, NODATA where no tile covers them."""
        out = np.full((r1 - r0, c1 - c0), NODATA, dtype=np.int16)
        for name, (_, lon_sw, lat_sw) in self.tiles.items():
            tc0 = (lon_sw + 180) * RES
            tr0 = (90 - lat_sw - TILE_H) * RES
            cc0, cc1 = max(c0, tc0), min(c1, tc0 + TILE_W * RES)
            rr0, rr1 = max(r0, tr0), min(r1, tr0 + TILE_H * RES)
            if cc0 >= cc1 or rr0 >= rr1:
                continue
            tile = self.load(name)
            out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = tile[rr0 - tr0:rr1 - tr0, cc0 - tc0:cc1 - tc0]
        return out


# --- state outlines --------------------------------------------------------------------------

def read_states():
    """Return {abbr: (name, [rings as (n,2) arrays in working longitude])} for the fifty states."""
    base = os.path.join(SRC, "cb500k", "cb_2023_us_state_500k")
    if not os.path.exists(base + ".shp"):
        die(f"missing {base}.shp; run make fetch")
    states = {}
    for sr in shapefile.Reader(base).iterShapeRecords():
        abbr = sr.record["STUSPS"]
        if abbr not in STATES:
            continue
        pts = np.array(sr.shape.points, dtype=np.float64)
        parts = list(sr.shape.parts) + [len(pts)]
        rings = []
        for a, b in zip(parts[:-1], parts[1:]):
            ring = pts[a:b].copy()
            ring[ring[:, 0] > 0, 0] -= 360
            if np.any(np.abs(np.diff(ring[:, 0])) > 1):
                die(f"{abbr}: a ring straddles the antimeridian unexpectedly")
            if abbr in CLIP:
                w, e, s, n = CLIP[abbr]
                if ring[:, 0].max() < w or ring[:, 0].min() > e or ring[:, 1].max() < s or ring[:, 1].min() > n:
                    continue
            rings.append(ring)
        states[abbr] = (sr.record["NAME"], rings)
    missing = STATES - set(states)
    if missing:
        die(f"states missing from the boundary file: {sorted(missing)}")
    return states


def rasterize(rings, lon0, lat0, d, cols, rows):
    """Boolean mask of cells whose centre is inside the rings (even-odd rule)."""
    x1 = np.concatenate([r[:-1, 0] for r in rings])
    y1 = np.concatenate([r[:-1, 1] for r in rings])
    x2 = np.concatenate([r[1:, 0] for r in rings])
    y2 = np.concatenate([r[1:, 1] for r in rings])
    keep = y1 != y2
    x1, y1, x2, y2 = x1[keep], y1[keep], x2[keep], y2[keep]
    slope = (x2 - x1) / (y2 - y1)
    lo, hi = np.minimum(y1, y2), np.maximum(y1, y2)
    mask = np.zeros((rows, cols), dtype=bool)
    for i in range(rows):
        lat = lat0 - (i + 0.5) * d
        hit = (lat >= lo) & (lat < hi)
        if not hit.any():
            continue
        xs = np.sort(x1[hit] + (lat - y1[hit]) * slope[hit])
        # cell j has centre lon0 + (j + 0.5) d; inside between crossing pairs
        ja = np.ceil((xs[0::2] - lon0) / d - 0.5).astype(int)
        jb = np.floor((xs[1::2] - lon0) / d - 0.5).astype(int)
        for a, b in zip(ja, jb):
            a, b = max(a, 0), min(b, cols - 1)
            if a <= b:
                mask[i, a:b + 1] = True
    return mask


# --- building one state ----------------------------------------------------------------------

def build_state(abbr, name, rings, mosaic):
    allpts = np.concatenate(rings)
    lon_w, lon_e = allpts[:, 0].min(), allpts[:, 0].max()
    lat_s, lat_n = allpts[:, 1].min(), allpts[:, 1].max()

    c0 = int(np.floor((lon_w + 180) * RES))
    c1 = int(np.ceil((lon_e + 180) * RES))
    r0 = int(np.floor((90 - lat_n) * RES))
    r1 = int(np.ceil((90 - lat_s) * RES))
    factor = max(1, -(-(c1 - c0) // MAX_COLS))         # ceil division
    c1 = c0 + -(-(c1 - c0) // factor) * factor
    r1 = r0 + -(-(r1 - r0) // factor) * factor
    lon0, lat0, d = -180 + c0 / RES, 90 - r0 / RES, 1 / RES

    full = mosaic.window(c0, c1, r0, r1)
    inside = rasterize(rings, lon0, lat0, d, c1 - c0, r1 - r0)
    if not inside.any():
        die(f"{abbr}: the outline does not cover any grid cell")

    elev = full.astype(np.float32)
    elev[full == NODATA] = 0                            # sea and unmapped cells sit at sea level
    rows, cols = (r1 - r0) // factor, (c1 - c0) // factor
    elev = elev.reshape(rows, factor, cols, factor).mean(axis=(1, 3))
    mask = inside.reshape(rows, factor, cols, factor).any(axis=(1, 3))
    grid = np.where(mask, np.rint(elev), NODATA).astype(np.int16)

    values = grid[mask]
    emin, emax = int(values.min()), int(values.max())
    if emax <= 0:
        die(f"{abbr}: no elevation above sea level, the tiles are probably wrong")

    fname = f"{abbr.lower()}.bin"
    write_grid(os.path.join(OUT, fname), grid, lon0, lat0, d * factor, emin, emax)
    return {
        "id": abbr.lower(), "abbr": abbr, "name": name, "file": fname,
        "cols": cols, "rows": rows, "cell": d * factor,
        "lon": [round(lon0, 6), round(lon0 + cols * d * factor, 6)],
        "lat": [round(lat0 - rows * d * factor, 6), round(lat0, 6)],
        "elev": [emin, emax],
        "bytes": 64 + 2 * rows * cols,
    }


def write_grid(path, grid, lon0, lat0, cell, emin, emax):
    """PLSR grid: a 64-byte little-endian header then int16 rows, north to south, west to east.

        0   'PLSR'            4 bytes
        4   version           u16 (1)
        6   cols              u16
        8   rows              u16
        10  reserved          u16
        12  lon0              f64  west edge of the first column (degrees, may be < -180)
        20  lat0              f64  north edge of the first row
        28  cell              f64  cell size in degrees (square cells)
        36  nodata            i16  (-32768, cells outside the state)
        38  elev min          i16  metres, inside the state
        40  elev max          i16
        42  padding to 64
    """
    rows, cols = grid.shape
    header = struct.pack("<4sHHHHdddhhh", b"PLSR", 1, cols, rows, 0, lon0, lat0, cell, NODATA, emin, emax)
    header += b"\0" * (64 - len(header))
    with open(path + ".part", "wb") as f:
        f.write(header)
        f.write(grid.astype("<i2").tobytes())
    os.replace(path + ".part", path)


# --- the national map for the front page --------------------------------------------------

# One picture 1000 units wide: the lower 48 in Mercator across the top, Alaska and Hawaii as
# insets in the lower left, all crossed by the same horizontal lines. Each sample along a line
# records the elevation there and which state it belongs to.
MAP_WIDTH, MAP_HEIGHT = 1000, 700
MAP_SAMPLES = 1200            # samples per line
MAP_SPACING = 6.0             # line spacing in map units
MAP_PANELS = [                # (name, states, (west, east, south, north) or None = the states' extent, (x0, y0, box width))
    ("conus", None, (-125.0, -66.9, 24.4, 49.5), (0, 0, MAP_WIDTH)),
    ("ak", ["AK"], None, (10, 440, 250)),
    ("hi", ["HI"], None, (280, 590, 150)),
]


def mercator(lat):
    return np.degrees(np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)))


def inverse_mercator(y):
    return np.degrees(2 * np.arctan(np.exp(np.radians(y))) - np.pi / 2)


def read_grid(path):
    """Read a PLSR file back (see write_grid)."""
    with open(path, "rb") as f:
        head = f.read(64)
        magic, version, cols, rows, _, lon0, lat0, cell, nodata, emin, emax = struct.unpack("<4sHHHHdddhhh", head[:42])
        if magic != b"PLSR" or version != 1:
            die(f"{path} is not a version 1 PLSR grid")
        data = np.frombuffer(f.read(2 * rows * cols), dtype="<i2").reshape(rows, cols)
    return {"cols": cols, "rows": rows, "lon0": lon0, "lat0": lat0, "cell": cell, "data": data, "emax": emax}


def simplify(pts, tol):
    """Douglas-Peucker: the subset of an (n, 2) polyline that stays within tol of it."""
    n = len(pts)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg, p, q = pts[a + 1:b], pts[a], pts[b]
        d = q - p
        length = np.hypot(d[0], d[1])
        if length == 0:
            dist = np.hypot(seg[:, 0] - p[0], seg[:, 1] - p[1])
        else:
            dist = np.abs((seg[:, 0] - p[0]) * d[1] - (seg[:, 1] - p[1]) * d[0]) / length
        i = int(np.argmax(dist))
        if dist[i] > tol:
            k = a + 1 + i
            keep[k] = True
            stack += [(a, k), (k, b)]
    return pts[keep]


OUTLINE_TOLERANCE = 0.35      # map units; the map is 1000 wide
OUTLINE_MIN_EXTENT = 1.2      # rings smaller than this (islets) are dropped


def outline_path(rings, project):
    """An SVG path string for a state's rings in map units, simplified for the map's scale."""
    parts = []
    for ring in rings:
        pts = project(ring)
        ext = pts.max(axis=0) - pts.min(axis=0)
        if ext.max() < OUTLINE_MIN_EXTENT:
            continue
        pts = simplify(pts, OUTLINE_TOLERANCE)
        if len(pts) < 4:
            continue
        parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts[:-1]) + "Z")
    return "".join(parts)


def build_map(states, rings):
    """Write site/data/map.bin and outlines.json from the state grids and outlines; return the
    map's entry for states.json.

    PLSM file: a 32-byte little-endian header, then int16 elevation (metres, 0 where no state)
    and uint8 state number (0 = none, else 1-based index into states.json) for every sample,
    line by line from the top, samples west to east.

        0   'PLSM'     4 bytes
        4   version    u16 (1)
        6   samples    u16 per line
        8   lines      u16
        10  reserved   u16
        12  width      f64 map units
        20  height     f64
        28  padding to 32
    """
    lines = int(round(MAP_HEIGHT / MAP_SPACING))
    spacing = MAP_HEIGHT / lines
    ys = (np.arange(lines) + 0.5) * spacing
    xs = (np.arange(MAP_SAMPLES) + 0.5) * MAP_WIDTH / MAP_SAMPLES
    X, Y = np.meshgrid(xs, ys)
    elev = np.zeros((lines, MAP_SAMPLES), dtype=np.float64)
    owner = np.zeros((lines, MAP_SAMPLES), dtype=np.uint8)
    grids = {s["abbr"]: read_grid(os.path.join(OUT, s["file"])) for s in states}
    boxes = {}
    outlines = {}
    for name, members, bounds, (x0, y0, w) in MAP_PANELS:
        members = members or [s["abbr"] for s in states if s["abbr"] not in ("AK", "HI")]
        if bounds is None:
            gs = [grids[m] for m in members]
            pad = 0.02 * max(g["cols"] * g["cell"] for g in gs)
            bounds = (min(g["lon0"] for g in gs) - pad, max(g["lon0"] + g["cols"] * g["cell"] for g in gs) + pad,
                      min(g["lat0"] - g["rows"] * g["cell"] for g in gs) - pad, max(g["lat0"] for g in gs) + pad)
        west, east, south, north = bounds
        m0, m1 = mercator(south), mercator(north)
        h = w * (m1 - m0) / (east - west)
        boxes[name] = [x0, y0, round(x0 + w, 1), round(y0 + h, 1)]
        inside = (X >= x0) & (X < x0 + w) & (Y >= y0) & (Y < y0 + h)
        lon = west + (X - x0) / w * (east - west)
        lat = inverse_mercator(m1 - (Y - y0) / h * (m1 - m0))
        half = (east - west) / w * (MAP_WIDTH / MAP_SAMPLES) / 2       # half a sample, in degrees

        def project(ring, x0=x0, y0=y0, w=w, h=h, west=west, east=east, m0=m0, m1=m1):
            return np.column_stack([x0 + (ring[:, 0] - west) / (east - west) * w,
                                    y0 + (m1 - mercator(ring[:, 1])) / (m1 - m0) * h])

        for abbr in members:
            g = grids[abbr]
            outlines[abbr.lower()] = outline_path(rings[abbr], project)
            number = 1 + next(i for i, s in enumerate(states) if s["abbr"] == abbr)
            valid = g["data"] != NODATA
            vals = np.where(valid, g["data"], 0).astype(np.float64)
            csum = np.concatenate([np.zeros((g["rows"], 1)), np.cumsum(vals, axis=1)], axis=1)
            cnum = np.concatenate([np.zeros((g["rows"], 1)), np.cumsum(valid, axis=1)], axis=1)
            r = np.floor((g["lat0"] - lat) / g["cell"]).astype(int)
            c0 = np.clip(np.floor((lon - half - g["lon0"]) / g["cell"]).astype(int), 0, g["cols"])
            c1 = np.clip(np.floor((lon + half - g["lon0"]) / g["cell"]).astype(int) + 1, 0, g["cols"])
            hit = inside & (owner == 0) & (r >= 0) & (r < g["rows"]) & (c1 > c0)
            rr, ca, cb = r[hit], c0[hit], c1[hit]
            n = cnum[rr, cb] - cnum[rr, ca]
            has = n > 0
            idx = np.flatnonzero(hit)[has]
            elev.flat[idx] = (csum[rr, cb] - csum[rr, ca])[has] / n[has]
            owner.flat[idx] = number
    missing = [s["abbr"] for i, s in enumerate(states) if not np.any(owner == i + 1)]
    if missing:
        die(f"states that do not appear on the map: {missing}")
    header = struct.pack("<4sHHHHdd", b"PLSM", 1, MAP_SAMPLES, lines, 0, float(MAP_WIDTH), float(MAP_HEIGHT))
    header += b"\0" * (32 - len(header))
    path = os.path.join(OUT, "map.bin")
    with open(path + ".part", "wb") as f:
        f.write(header)
        f.write(np.rint(elev).astype("<i2").tobytes())
        f.write(owner.tobytes())
    os.replace(path + ".part", path)
    opath = os.path.join(OUT, "outlines.json")
    with open(opath + ".part", "w") as f:
        json.dump({"version": 1, "outlines": outlines}, f, separators=(",", ":"))
    os.replace(opath + ".part", opath)
    return {"file": "map.bin", "outlines": "outlines.json", "width": MAP_WIDTH, "height": MAP_HEIGHT,
            "samples": MAP_SAMPLES, "lines": lines, "boxes": boxes,
            "bytes": 32 + 3 * lines * MAP_SAMPLES, "outlineBytes": os.path.getsize(opath)}


def main(argv):
    wanted = {a.upper() for a in argv} or STATES
    unknown = wanted - STATES
    if unknown:
        die(f"unknown state(s): {sorted(unknown)}")
    os.makedirs(OUT, exist_ok=True)
    states = read_states()
    mosaic = Mosaic()
    index_path = os.path.join(OUT, "states.json")
    index = {"version": DATA_VERSION, "states": []}
    if wanted != STATES and os.path.exists(index_path):
        with open(index_path) as f:
            index = json.load(f)
        index["states"] = [s for s in index["states"] if s["abbr"] not in wanted]
    total = 0
    for abbr in sorted(wanted, key=lambda a: states[a][0]):
        name, rings = states[abbr]
        print(f"{abbr} {name}")
        entry = build_state(abbr, name, rings, mosaic)
        total += entry["bytes"]
        index["states"].append(entry)
        print(f"  {entry['cols']} x {entry['rows']} cells, {entry['elev'][0]}..{entry['elev'][1]} m, {entry['bytes'] / 1e6:.2f} MB")
    index["states"].sort(key=lambda s: s["name"])
    if len(index["states"]) == len(STATES):
        print("national map")
        index["map"] = build_map(index["states"], {abbr: rings for abbr, (_, rings) in states.items()})
        print(f"  {index['map']['lines']} lines of {index['map']['samples']} samples, {index['map']['bytes'] / 1e6:.2f} MB;"
              f" outlines {index['map']['outlineBytes'] / 1e3:.0f} kB")
    else:
        index.pop("map", None)
        print(f"skipping the national map: only {len(index['states'])} of {len(STATES)} states are built")
    with open(index_path + ".part", "w") as f:
        json.dump(index, f, indent=1)
    os.replace(index_path + ".part", index_path)
    print(f"wrote {len(index['states'])} states, {total / 1e6:.1f} MB, to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
