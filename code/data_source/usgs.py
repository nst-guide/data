import math
import re
from pathlib import Path
from subprocess import run
from typing import List, Union
from urllib.request import urlretrieve

import fiona
import geopandas as gpd
import pandas as pd
import rasterio
from geopandas import GeoDataFrame as GDF
from geopandas.tools import sjoin
from scipy.interpolate import interp2d
from shapely.geometry import LineString

from .base import DataSource
from .grid import OneDegree

try:
    import geom
except ModuleNotFoundError:
    # Development in IPython
    import sys
    sys.path.append('../')
    import geom


class NationalElevationDataset(DataSource):
    """
    I compared these interpolated elevations with those contained in the
    Halfmile data for Sec A and the mean difference in elevation per point. 90%
    less than 5 meter difference.

    No interpolation        Linear interpolation:   Cubic with num_buffer=2
    count    1987.000000    count    1987.000000    count    1987.000000
    mean        1.964173    mean        1.778928    mean        1.776176
    std         2.188573    std         2.187626    std         2.227961
    min         0.000249    min         0.000076    min         0.000052
    25%         0.408596    25%         0.224535    25%         0.193832
    50%         1.192173    50%         0.834920    50%         0.756697
    75%         2.861689    75%         2.745461    75%         2.795144
    max        20.888750    max        19.116444    max        19.576745
    dtype: float64          dtype: float64          dtype: float64
    """
    def __init__(self):
        super(NationalElevationDataset, self).__init__()

        self.raw_dir = self.data_dir / 'raw' / 'elevation'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, trail, overwrite: bool = False):
        """Download 1/3 arc-second elevation data

        Args:
            overwrite: whether to overwrite existing files. If False, only
                downloads new copy if neither the ZIP file or extracted IMG file
                already exist.

        NOTE: some urls are different. I.e. for n37w119, the filename is
        n37w119.zip, not USGS_NED_13_n37w119_IMG.zip. Apparently this data was
        published in 2013, not 2018, which is why it has a different name. I
        haven't implemented a way to check this automatically yet.
        """
        urls = sorted(self._get_download_urls(trail=trail))
        for url in urls:
            # 50th degree latitudes is outside the US
            if 'n50w121' in url:
                continue

            save_path = self.raw_dir / (Path(url).stem + '.zip')
            extracted_path = self.raw_dir / (Path(url).stem + '.img')
            if overwrite or (not save_path.exists()
                             and not extracted_path.exists()):
                urlretrieve(url, save_path)

    def _get_download_urls(self, trail):
        """Create download urls
        """
        intersecting_bboxes = OneDegree().get_cells(trail)

        # The elevation datasets are identified by the _UPPER_ latitude and
        # _LOWER_ longitude, i.e. max and min repsectively
        baseurl = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation'
        baseurl += '/13/IMG/'
        urls = []
        for bbox in intersecting_bboxes:
            lat = str(int(bbox.bounds[3]))
            lon = str(int(abs(bbox.bounds[0])))
            url = baseurl + f'USGS_NED_13_n{lat}w{lon}_IMG.zip'
            urls.append(url)

        return urls

    def files(self, ext):
        return sorted(self.raw_dir.glob(f'*IMG{ext}'))

    def extract(self):
        """Unzip elevation ZIP files

        TODO: name of .img file inside ZIP can change; use ZipFile to find the
        .img file
        TODO delete ZIP file after extract?
        Only extract .img file from ZIP file to keep directory clean
        """
        zip_fnames = self.files('.zip')
        for zip_fname in zip_fnames:
            img_name = zip_fname.stem + '.img'
            out_dir = zip_fname.parents[0]
            cmd = ['unzip', '-o', zip_fname, img_name, '-d', out_dir]
            run(cmd, check=True)

    def query(
            self,
            lon: float,
            lat: float,
            num_buffer: int = 1,
            interp_kind: str = 'linear') -> float:
        """Query elevation data for given point

        NOTE: if you want to interpolate over neighboring squares, you can
        expand then window when reading, then get the actual xy position as lat
        lon, then get the neighboring positions as lat lon too

        Args:
            lon: longitude
            lat: latitude
            num_buffer: number of bordering cells around (lon, lat) to use when interpolating
            interp_kind: kind of interpolation. Passed to scipy.interpolate.interp2d. Can be ['linear’, ‘cubic’, ‘quintic']

        Returns elevation for point (in meters)
        """
        # Find file given lon, lat
        s = f'n{int(abs(math.ceil(lat)))}w{int(abs(math.floor(lon)))}'
        fname = [x for x in self.files('.img') if s in str(x)]
        assert len(fname) == 1, 'More than one elevation file matched query'
        fname = fname[0]

        # Read metadata of file
        dataset = rasterio.open(fname)

        # Find x, y of elevation square inside raster
        x, y = dataset.index(lon, lat)

        # Make window include cells around it
        # The number of additional cells depends on the value of num_buffer
        # When num_buffer==1, an additional 8 cells will be loaded and
        # interpolated on;
        # When num_buffer==2, an additional 24 cells will be loaded and
        # interpolated on, etc.
        # When using kind='linear' interpolation, I'm not sure if having the
        # extra cells makes a difference; ie if it creates the plane based only
        # on the closest cells or from all. When using kind='cubic', it's
        # probably more accurate with more cells.

        minx = x - num_buffer if x >= num_buffer else x
        maxx = x + num_buffer if x + num_buffer <= dataset.width else x
        miny = y - num_buffer if y >= num_buffer else y
        maxy = y + num_buffer if y + num_buffer <= dataset.width else y

        # Add +1 to deal with range() not including end
        maxx += 1
        maxy += 1

        window = ([minx, maxx], [miny, maxy])
        val_arr = dataset.read(1, window=window)

        msg = 'array has too few or too many values'
        max_num = 2 * num_buffer + 1
        assert (1 <= val_arr.shape[0] <=
                max_num) and (1 <= val_arr.shape[1] <= max_num), msg

        # Now linearly interpolate
        # Get actual lat/lons
        # Note that zipping together means that I get the diagonal, i.e. one of
        # each of x, y. Since these aren't projected coordinates, but rather the
        # original lat/lons, this is a regular grid and this is ok.
        lonlats = [
            dataset.xy(x, y)
            for x, y in zip(range(minx, maxx), range(miny, maxy))
        ]
        lons = [x[0] for x in lonlats]
        lats = [x[1] for x in lonlats]

        fun = interp2d(x=lons, y=lats, z=val_arr, kind=interp_kind)
        value = fun(lon, lat)
        return value[0]


class USGSHydrography(DataSource):
    def __init__(self):
        super(USGSHydrography, self).__init__()
        self.raw_dir = self.data_dir / 'raw' / 'hydrology'
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.hu2_list = [16, 17, 18]

    def download(self, trail: gpd.GeoDataFrame, overwrite=False):
        self._download_boundaries(overwrite=overwrite)
        self._download_nhd_for_line(line=trail, overwrite=overwrite)

    def load_nhd_iter(self) -> str:
        """Iterator to load NHD data for polygons that intersect the trail

        For now, this just yields the _path_ to the file, instead of the opened
        file, because I can only open a single layer of the GDB at a time, and
        I'll probably want more than one layer.
        """
        # Get all files in the raw hydrography folder conforming to NHD HU8 file
        # name
        # NOTE: If in the future I add more trails, this won't be performant,
        # because it could be trying to match PCT water boundaries to another
        # trail.
        name_regex = re.compile(r'^NHD_H_\d{8}_HU8_GDB.zip$')
        nhd_files = [
            path for path in self.raw_dir.iterdir()
            if name_regex.search(path.name)
        ]
        for f in nhd_files:
            yield f

    def nhd_files_for_geometry(self, geometry):
        if isinstance(geometry, gpd.GeoDataFrame):
            hu8_units = self._get_HU8_units_for_gdf(geometry)
        else:
            hu8_units = self._get_HU8_units_for_geometry(geometry)

        hu8_ids = hu8_units['HUC8'].unique()
        files = [
            self.raw_dir / f'NHD_H_{hu8_id}_HU8_GDB.zip' for hu8_id in hu8_ids
        ]
        msg = 'Not all NHD files exist'
        assert all(f.exists() for f in files), msg

        return files

    def read_files(self, files: List[Path], layer: str) -> GDF:
        """

        Args:
            - layer: Probably one of these first three:

                - NHDPoint
                - NHDFlowline
                - NHDArea

                These are more layers in the file, but probably lesser-used:

                - NHDLine
                - NHDStatus
                - NHDReachCrossReference
                - NHDReachCodeMaintenance
                - NHDFlowlineVAA
                - NHDFlow
                - NHDFCode
                - ExternalCrosswalk
                - NHDFeatureToMetadata
                - NHDMetadata
                - NHDSourceCitation
                - NHDLineEventFC
                - NHDPointEventFC
                - NHDAreaEventFC
                - NHDWaterbody
                - NHDVerticalRelationship

        """
        gdfs = [gpd.read_file(f, layer=layer).to_crs(epsg=4326) for f in files]
        return gpd.GeoDataFrame(pd.concat(gdfs))

    def _download_boundaries(self, overwrite):
        """
        Hydrologic Units range from 1-18. The PCT only covers parts of 16, 17,
        and 18. For other trails you'd want to cover the entire US, then get
        boundaries from it.
        """
        baseurl = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/'
        baseurl += 'WBD/HU2/GDB/'
        for hu2_id in self.hu2_list:
            name = f'WBD_{hu2_id}_HU2_GDB.zip'
            url = baseurl + name
            path = self.raw_dir / name
            if overwrite or (not path.exists()):
                urlretrieve(url, path)

    def _download_nhd_for_line(self, line: Union[LineString, GDF], overwrite):
        """Download National Hydrography Dataset for trail

        Downloads NHD files within 2 miles of trail
        """
        if not isinstance(line, gpd.GeoDataFrame):
            line = gpd.GeoDataFrame([], lineetry=[line])
            line.crs = {'init': 'epsg:4326'}

        buf = geom.buffer(line, distance=2, unit='mile').unary_union
        gdfs = self._get_HU8_units_for_geometry(buf)
        hu8_ids = gdfs['HUC8'].unique()

        baseurl = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/'
        baseurl += 'NHD/HU8/HighResolution/GDB/'
        for hu8_id in hu8_ids:
            name = f'NHD_H_{hu8_id}_HU8_GDB.zip'
            url = baseurl + name
            path = self.raw_dir / name
            if overwrite or (not path.exists()):
                urlretrieve(url, path)

    def _get_HU8_units_for_geometry(self, geometry):
        """Find HU8 units that geometry intersects"""
        # Convert geometry to gdf
        if not isinstance(geometry, gpd.GeoDataFrame):
            geometry = gpd.GeoDataFrame([], geometry=[geometry])
            geometry.crs = {'init': 'epsg:4326'}

        return self._get_HU8_units_for_gdf(geometry)

    def _get_HU8_units_for_gdf(self, gdf: GDF) -> GDF:
        """Get HU8 units that intersect gdf

        Args:
            - gdf: GeoDataFrame to intersect with

        Returns:
            GeoDataFrame of HU8 boundaries that intersect gdf
        """
        gdf = gdf.to_crs(epsg=4326)

        # First find HU2 units that intersect gdf
        intersecting_hu2 = []
        for hu2_id in self.hu2_list:
            hu2 = self._load_HU8_boundaries(hu2_id=hu2_id, region_size='HU2')
            hu2 = hu2.to_crs(epsg=4326)
            intersecting_hu2.append(sjoin(hu2, gdf, how='inner'))

        int_hu2_gdf = gpd.GeoDataFrame(pd.concat(intersecting_hu2))
        hu2_ids = int_hu2_gdf['HUC2'].values

        # Npw just look within the large regions that I know gdf is in
        intersecting_hu8 = []
        for hu2_id in hu2_ids:
            hu8 = self._load_HU8_boundaries(hu2_id=hu2_id, region_size='HU8')
            hu8 = hu8.to_crs(epsg=4326)
            intersecting_hu8.append(sjoin(hu8, gdf, how='inner'))

        return gpd.GeoDataFrame(pd.concat(intersecting_hu8))

    def _load_HU8_boundaries(self, hu2_id, region_size: str) -> GDF:
        """Load Subregion Watershed boundaries

        Watershed boundaries are split up by USGS into a hierarchy of smaller
        and smaller areas. In _download_boundaries, the watershed boundary
        dataset is downloaded for `HU2` (Region), which is the second-largest
        collection, behind the full national file.

        In order to download the minimum amount of data from the National
        Hydrology Dataset (NHD), I want to download those at the `HU8`
        (Subbasin) level, so that I'm not downloading data for areas far from
        the trail. (`HU8` is the smallest area files that exist for NHD.) So
        here, I'm just extracting the `HU8` boundaries from the larger `HU2`
        watershed boundary datasets.

        This function allows for getting different region sizes, i.e. HU2, HU4,
        HU8, etc. HU2 is useful in order to quickly see if the section of trail
        is anywhere near this region.

        Args:
            hu2_id: two-digit ID for large HU2 region
            region_size: boundary region size. I.e. "HU2" for large region, or
              "HU8" for smaller subbasins

        """
        name = f'WBD_{hu2_id}_HU2_GDB.zip'
        path = self.raw_dir / name
        layers = fiona.listlayers(str(path))
        msg = f'{region_size} boundaries not in WBD dataset'
        assert f'WBD{region_size}' in layers, msg

        return gpd.read_file(path, layer=f'WBD{region_size}')
