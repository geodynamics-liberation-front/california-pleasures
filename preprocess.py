#!/usr/bin/env python3

from functools import reduce
from os import listdir
import re
from bs4 import BeautifulSoup
import rasterio
import numpy as np

TIF_DIR = './geotifs'
LAT_LON_RE = re.compile(".*([ns]\\d{1,2})([ew]\\d{1,3}).*")

if __name__ == "__main__":
    # Extract the california border
    with open('US_State_Boundaries.kml') as f:
        soup = BeautifulSoup(f)

    # Extract the coordinates, select the bigest
    coords = reduce(lambda a,b: a if len(a) > len(b) else b, soup.find("name",text="California").parent('coordinates'))
    # print(coords)
    lon, lat = [np.array(l) for l in list(zip(*[[float(f) for f in c.split(',')] for c in coords.text.split()]))]
    np.save('ca_border_lon.npy', lon)
    np.save('ca_border_lat.npy', lat)

    elev_max = -1_000_000
    elev_min =  1_000_000
    lon_max  = -1_000_000
    lon_min  =  1_000_000
    lat_max  = -1_000_000
    lat_min  =  1_000_000

    frames_lon_min =  1000
    frames_lon_max = -1000
    frames_lat_min =  1000
    frames_lat_max = -1000

    for f in [f for f in sorted(listdir(TIF_DIR)) if re.search('.tif',f)]:
        print(f)
        dataset = rasterio.open(f'{TIF_DIR}/{f}')
        m = LAT_LON_RE.match(dataset.name)
        frame_lon = int(m.group(2).replace('w', '-').replace('e', ''))
        frames_lon_min = min(frames_lon_min, frame_lon)
        frames_lon_max = max(frames_lon_max, frame_lon)
        frame_lat = int(m.group(1).replace('s', '-').replace('n', ''))
        frames_lat_min = min(frames_lat_min, frame_lat)
        frames_lat_max = max(frames_lat_max, frame_lat)

        frame_width = dataset.width
        frame_height = dataset.height
        print(dataset.bounds)

        band = dataset.read(1)
        # nan the 'bad values' -999999
        band[band == -999999] = np.nan

        elev_max=max(elev_max, np.nanmax(band))
        elev_min=min(elev_min, np.nanmin(band))

        lon_max=max(lon_max, dataset.bounds.right)
        lon_min=min(lon_min, dataset.bounds.left)

        lat_max=max(lat_max, dataset.bounds.top)
        lat_min=min(lat_min, dataset.bounds.bottom)
        dataset.close()

    with open('california_dem.py','w') as f:
        f.write(f"""import numpy as np

ELEV_MAX       = {elev_max}
ELEV_MIN       = {elev_min}
LON_MAX        = {lon_max}
LON_MIN        = {lon_min}
LAT_MAX        = {lat_max}
LAT_MIN        = {lat_min}
CA_BORDER_LON  = np.load('ca_border_lon.npy')
CA_BORDER_LAT  = np.load('ca_border_lat.npy')
FRAME_WIDTH    = {frame_width}
FRAME_HEIGHT   = {frame_height}
FRAMES_LON_MIN = {frames_lon_min}
FRAMES_LON_MAX = {frames_lon_max}
FRAMES_LAT_MIN = {frames_lat_min}
FRAMES_LAT_MAX = {frames_lat_max}
""")
