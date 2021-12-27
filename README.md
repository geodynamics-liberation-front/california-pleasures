# california-pleasures
Creates an image of California in the style of Joy Division's 'Unknown Pleasures' album cover.

## Instructions
Commands are issued from the project directory.

### Data
Download the border and elevation data.  These scripts download data for California. 
This might take some time depending on your Internet speed
```
./download.sh
cd geotif 
./download.sh
cd ..
```

### Python
This project uses Anaconda to manage the environment
```
conda env create --file environment.yml --prefix ./env
```
Now activate the environment
```
conda activate ./env
```

### Data II
Preprocess the data
```
./preprocess.py
```

Generate the SVG
```
./ca_pleasures.py
```

## Customize
*COMING SOON*

## Data Sources
### Elevation Data
FROM USGS 3D Elevation Progamr
https://apps.nationalmap.gov/downloader/#/

### Borders
Census TIGER retrieved from 
https://hifld-geoplatform.opendata.arcgis.com/datasets/us-state-boundaries/explore?location=9.386497%2C0.314297%2C2.77
https://opendata.arcgis.com/api/v3/datasets/54ad5ca9349947f88c5879a2b923120b_0/downloads/data?format=kml&spatialRefId=4326
