# create-database

## Overview

This repository contains code for data pipelines to generate map waypoints and layers of interest from open map data sources.

### Data Sources

- Town Boundaries: for now, these are drawn by hand using local trail knowledge and <https://geojson.io> and saved to `data/pct/polygon/bound/town/{ca,or,wa}/*.geojson`.
- [OpenStreetMap](openstreetmap.org): I use OSM for trail information and town waypoints.
- [Halfmile](pctmap.net): Halfmile has accurate route information and a few
  thousand waypoints for the trail. I have yet to hear final confirmation that
  this is openly licensed, but I've seen other projects using this data, and am
  optimistic that the use will be ok.
- USFS: The US Forest Service is the US governmental body that officially
  stewards the Pacific Crest Trail. As such, they keep an official centerline of
  the trail, but it is much less accurate than the Halfmile or OpenStreetMap
  centerlines. The PCT USFS page is here: <https://www.fs.usda.gov/pct/>.
- GPSTracks: On my hike of the PCT in 2019, I recorded my own GPS data,
  generally at 5-second intervals. This raw data has been copied into
  `data/raw/tracks`. While it's generally not accurate enough to use as an
  official centerline for an app, it will be helpful to use to geocode photos,
  and thus fill in waypoints that are missing from open data sources.
- Wilderness Boundaries: Wilderness boundaries are retrieved from <https://wilderness.net>.
- National Park Boundaries: National Park boundaries are retrieved from the [NPS open data portal](https://public-nps.opendata.arcgis.com/datasets/b1598d3df2c047ef88251016af5b0f1e_0).
- National Forest Boundaries: National Forest boundaries are retrieved from the [USFS website](https://data.fs.usda.gov/geodata/edw/datasets.php?dsetCategory=boundaries), under the heading _Administrative Forest Boundaries_.
- State Boundaries: State boundaries from the Census' [TIGER dataset](https://www2.census.gov/geo/tiger/TIGER2017/STATE/).
- Cell Towers: Cell tower data come from [OpenCellID](www.opencellid.org).
  Ideally at some point I'll implement a simple line-of-sight algorithm and then
  calculate where on the trail has cell service.
- Lightning Counts: daily lightning counts for 0.1-degree bins are available
  since ~1986 from
  [NOAA](https://www.ncdc.noaa.gov/data-access/severe-weather/lightning-products-and-services).
  Note that the raw data of where every lightning strike hits is closed source
  and must be purchased, but a NOAA contract lets daily extracts be made public.
- Transit: I get transit data from the [Transitland](transit.land) database.
  This is a bit easier than working with raw GTFS (General Transit Feed
  Specification) data, and they've done a bit of work to deduplicate data and
  connect the same stops in different data extracts from different providers.
- National Elevation Dataset: In the US, the most accurate elevation data comes from the USGS's [3D Elevation Program](https://www.usgs.gov/core-science-systems/ngp/3dep/data-tools). They have a seamless Digital Elevation Model (DEM) at 1/3 arc-second resolution, which is about 10 meters.
- USGS Hydrography: The USGS's [National Hydrography products](https://www.usgs.gov/core-science-systems/ngp/national-hydrography/about-national-hydrography-products) are the premier water source datasets for the US. The Watershed Boundary dataset splits the US into a pyramid of smaller and smaller hydrologic regions. I first use the Watershed Boundary dataset to find the watersheds that the PCT passes through, then go to the National Hydrography dataset to find all streams, lakes, and springs near the trail.
- [PCT Water Report](pctwater.net): The PCT water report is an openly-licensed set of spreadsheets with reports from hikers of which water sources are flowing.
- EPA AirNow: The EPA has an [API](https://docs.airnowapi.org/) where you can access current air quality regions.
- GeoMAC: GeoMAC is the standard for accessing historical and current wildfire boundaries.
- CalFire
- Recreation.gov: Recreation.gov has an API for accessing information about features in National Forests.

### Folder Structure

- `data.py`
- `dev.py`
- `geom.py`
- `grid.py`
- `keplergl_config.json`
- `parse.py`
- `tiles.py`
- `trail.py`
- `util.py`




### OpenStreetMap

1. Download extracts from Geofabrik. PBF is fine. E.g.

    - Southern California: http://download.geofabrik.de/north-america/us/california/socal.html
    - Northern California: http://download.geofabrik.de/north-america/us/california/norcal.html
    - Oregon: http://download.geofabrik.de/north-america/us/oregon.html
    - Washington: http://download.geofabrik.de/north-america/us/washington.html
2. Use `osmconvert` to get an extract. Use `--out-o5m` because `osmfilter` in the next step can only read `.o5m` or `.osm` and the former has much smaller file sizes and is faster to read. Use `-b` to use a bounding box, or `-B` to supply a polygon. I.e.:

    ```
    osmconvert washington-latest.pbf --out-o5m -b=-122.231441,45.455465,-119.792476,49.040709 > washington.o5m
    osmconvert socal-latest.osm.pbf --out-o5m -b=-116.951373,32.524291,-115.858233,33.998650 > socal.o5m
    ```

3. Use `osmfilter` to get areas of interest.

    ```
    osmfilter socal.o5m  --keep-relations="@id=1225378" --keep-ways= --keep-nodes= -o=pct-socal.osm
    ```

osmconvert washington-latest.osm --out-o5m -b=-122.231441,45.455465,-119.792476,49.040709 > washington.o5m
