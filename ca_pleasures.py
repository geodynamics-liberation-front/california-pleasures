#!/usr/bin/env python3

from os import listdir
import re
import rasterio
import numpy as np
import california_dem as dem

LAT_LON = re.compile(".*([ns]\\d{1,2})([ew]\\d{1,3}).*")

FRAMES_LON_WIDTH = dem.FRAMES_LON_MAX - dem.FRAMES_LON_MIN + 1
FRAMES_LAT_WIDTH = dem.FRAMES_LAT_MAX - dem.FRAMES_LAT_MIN + 1
LAT_LINE_LENGTH =  dem.FRAME_WIDTH * FRAMES_LON_WIDTH
ELEVATION_SCALE = 1/(dem.ELEV_MAX - dem.ELEV_MIN)

def nan_helper(y):
    """Helper to handle indices and logical indices of NaNs.

    Input:
        - y, 1d numpy array with possible NaNs
    Output:
        - nans, logical indices of NaNs
        - index, a function, with signature indices= index(logical_indices),
          to convert logical indices of NaNs to 'equivalent' indices
    Example:
        >>> # linear interpolation of NaNs
        >>> nans, x= nan_helper(y)
        >>> y[nans]= np.interp(x(nans), x(~nans), y[~nans])
    """

    return np.isnan(y), lambda z: z.nonzero()[0]


def calculateIntersections(lats):
    lons = [[] for i in range(lats.size)]
    for i in range(dem.CA_BORDER_LAT.size-1):
        for j, lat in enumerate(lats):
            if ((lat > dem.CA_BORDER_LAT[i] and lat < dem.CA_BORDER_LAT[i+1]) or
               (lat < dem.CA_BORDER_LAT[i] and lat > dem.CA_BORDER_LAT[i+1])):
                lons[j].append(dem.CA_BORDER_LON[i])
    return np.array([[min(values), max(values)] for values in lons])


def findTiffs(lat, d="./geotifs"):
    return sorted(
        [f'{d}/{f}' for f in listdir(d) if re.search(f'n{int(lat+1)}', f)],
        key=lambda f: float(re.search('[ew](\\d{1,3})_', f).group(1)),
        reverse=True
    )


def getFrames(lat):
    frame_lat = int(lat+1)
    if frame_lat == getFrames.lat:
        return getFrames.frames
    getFrames.lat = frame_lat
    if getFrames.frames is not None:
        for dataset, band in getFrames.frames:
            dataset.close()
    datasets = [rasterio.open(f) for f in findTiffs(lat)]
    bands = [ds.read(1) for ds in datasets]
    getFrames.frames = list(zip(datasets, bands))
    return getFrames.frames


getFrames.lat = None
getFrames.frames = None


def getElev(lat, mask):
    print(f'getElev({lat},{mask})')
    lon = np.linspace(dem.FRAMES_LON_MIN, dem.FRAMES_LON_MAX+1, num=LAT_LINE_LENGTH)
    elev = np.zeros(LAT_LINE_LENGTH)

    frames = getFrames(lat)
    for dataset, band in frames:
        m = LAT_LON.match(dataset.name)
        frame_lon = int(m.group(2).replace('w', '-').replace('e', ''))
        offset = (frame_lon - dem.FRAMES_LON_MIN)*dem.FRAME_WIDTH
        row, _ = dataset.index(
            (dataset.bounds.left+dataset.bounds.right)/2,
            lat
        )
        e = band[row]
        e[e == -999999] = np.nan
        nans, x = nan_helper(e)
        e[nans] = np.interp(x(nans), x(~nans), e[~nans])
        e = e*ELEVATION_SCALE+lat
        elev[offset:offset+dem.FRAME_WIDTH] = e

    elev[lon < mask[0]] = lat
    elev[lon > mask[1]] = lat

    return lon, elev


def subsample(values, scale):
    extra = values.size % scale
    left = extra//2
    right = extra-left
    return values[left:-right] \
        .reshape((values.size-extra)//scale, scale) \
        .mean(axis=1)


def mercator(y):
    y = y*np.pi/180
    y = np.log(np.tan(np.pi/4 + y/2))
    return y * 180/np.pi


def toPath(x, y, id, style="stroke:#ff0000;"):
    points = ' '.join([f'{i:0.3f},{j:0.3f}' for i, j in zip(x, y)])
    return f'<path d="M {points}" id="{id}" style="{style}"/>'


def svg(lats):
    intersections = calculateIntersections(lats)
    print('Border Intersections')
    print(intersections)

    style = ';'.join([
        'stroke:#ffffff',
        'stroke-width:0.02',
        'stroke-miterlimit:4',
        'stroke-dasharray:none',
        'fill:#000000',
        'fill-opacity:1',
        'stroke-opacity:1'
    ])
    paths = []
    x_min = 1_000_000
    x_max = -1_000_000
    y_min = 1_000_000
    y_max = -1_000_000

    for lat, intersection in zip(lats, intersections):
        x, y = getElev(lat, intersection)
        x = subsample(x, 100)
        x_min = min(x_min, x.min())
        x_max = max(x_max, x.max())
        y = subsample(y, 100)
        y = mercator(y)
        y_min = min(y_min, y.min())
        y_max = max(y_max, y.max())
        paths.append(toPath(x, y, f'lat_{lat:0.3f}', style))
    paths = "\n".join(paths)

    x_min = x_min - 0.5
    x_max = x_max + 0.5
    y_min = y_min - 0.5
    y_max = y_max + 0.5

    width = x_max - x_min
    height = y_max - y_min

    rect = f'<rect style="fill:#000000;" id="bg" width="{width}" height="{height}" x="0" y="0" />'
    transform = f'scale(1, -1) translate({-x_min} {-y_max})'

    svg_text = f"""<?xml version="1.0" encoding="utf-8" standalone="no"?>
    <!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
    <svg viewBox="0 0 {width} {height}" width="{100*width:0.0f}" height="{100*height:0.0f}" xmlns="http://www.w3.org/2000/svg">
        {rect}
        <g id="figure_1" transform="{transform}">
{paths}
        </g>
    </svg>
"""
    with open('ca_pleasures.svg', 'w') as f:
        f.write(svg_text)


if __name__ == "__main__":
    lats = np.arange(41.9, 32.5, -0.2)
    print(f'Ploting elevation for latitudes {lats}')
    svg(lats)
