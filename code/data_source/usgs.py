import re
from pathlib import Path
from subprocess import run
from typing import List, Union
from urllib.request import urlretrieve

import demquery
import fiona
import geopandas as gpd
import pandas as pd
import requests
from geopandas import GeoDataFrame as GDF
from geopandas.tools import sjoin
from shapely.geometry import LineString, Polygon

from .base import DataSource

try:
    import geom
    from grid import USGSElevGrid
except ModuleNotFoundError:
    # Development in IPython
    import sys
    sys.path.append('../')
    import geom
    from grid import USGSElevGrid


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

        TODO: update to use the TNM API
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

        Args:
            - trail: geometry, not gdf
        """
        cells = USGSElevGrid(trail)

        # The elevation datasets are identified by the _UPPER_ latitude and
        # _LOWER_ longitude, i.e. max and min repsectively
        baseurl = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation'
        baseurl += '/13/IMG/'
        urls = []
        for cell in cells:
            lat = str(int(cell.bounds[3]))
            lon = str(int(abs(cell.bounds[0])))
            url = baseurl + f'USGS_NED_13_n{lat}w{lon}_IMG.zip'
            urls.append(url)

        return urls

    def files(self, ext='.img'):
        return sorted(self.raw_dir.glob(f'*{ext}'))

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

    def query(self, coords, interp_kind=None):
        """Query elevation data for coordinates

        Args:
            - coords: list of tuples in longitude, latitude order
            - interp_kind: kind of interpolation. Passed to
                scipy.interpolate.interp2d. Can be [None, 'linear’, ‘cubic’,
                ‘quintic']

        Returns elevations for coordinates (in meters)
        """
        dem_paths = self.files()
        query = demquery.Query(dem_paths)
        elevations = query.query_points(coords, interp_kind=interp_kind)
        return elevations


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


class MapIndices(DataSource):
    """docstring for MapIndices"""
    def __init__(self):
        super(MapIndices, self).__init__()
        self.raw_dir = self.data_dir / 'raw' / 'usgs'
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.states = ['Washington', 'Oregon', 'California']

    def _stub(self, state):
        return f'MAPINDICES_{state}_State_GDB.zip'

    def download(self, overwrite=False):
        """Download Map Indices for each state
        """
        baseurl = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/MapIndices/GDB'
        for state in self.states:
            stub = self._stub(state)
            url = f'{baseurl}/{stub}'
            local_path = self.raw_dir / stub
            if overwrite or (not local_path.exists()):
                urlretrieve(url, local_path)

    def read(self, layer):
        """Read layer from Map Indices file

        Args:
            - layer: Must be one of:
                - 15Minute
                - 1X1Degree
                - 1X2Degree
                - 3_75Minute
                - 30X60Minute
                - 7_5Minute
        """
        valid_layers = [
            '15Minute', '1X1Degree', '1X2Degree', '3_75Minute', '30X60Minute',
            '7_5Minute'
        ]

        msg = f'valid layers are: {valid_layers}'
        assert layer in valid_layers, msg
        layer = f'CellGrid_{layer}'

        files = []
        for state in self.states:
            stub = self._stub(state)
            file = self.raw_dir / stub
            files.append(file)

        gdfs = [gpd.read_file(f, layer=layer).to_crs(epsg=4326) for f in files]
        return gpd.GeoDataFrame(pd.concat(gdfs))


class NationalMapAPI(DataSource):
    """Wrapper for National Map API

    Written documentation:
    https://viewer.nationalmap.gov/help/documents/TNMAccessAPIDocumentation/TNMAccessAPIDocumentation.pdf

    Playground:
    https://viewer.nationalmap.gov/tnmaccess/api/index
    """
    def __init__(self):
        super(NationalMapAPI, self).__init__()

        self.baseurl = 'https://viewer.nationalmap.gov/tnmaccess/api'

    def search_datasets(self, bbox):
        url = f'{self.baseurl}/datasets'
        params = {
            'bbox': ','.join(map(str, bbox.bounds)),
        }
        r = requests.get(url)
        return r.json()

    def search_products(self, bbox: Polygon, product_name: str):
        """Search the products endpoint of the National Map API

        Args:
            - bbox:
        """
        url = f'{self.baseurl}/products'

        products_xw = {
            'nbd': 'National Boundary Dataset (NBD)',
            'nhd': 'National Hydrography Dataset (NHD) Best Resolution',
            'wbd': 'National Watershed Boundary Dataset (WBD)',
            'naip': 'USDA National Agriculture Imagery Program (NAIP)',
            'ned1/3': 'National Elevation Dataset (NED) 1/3 arc-second',
            'ned1': 'National Elevation Dataset (NED) 1 arc-second',
        }
        product_kw = products_xw.get(product_name)
        if product_kw is None:
            msg = 'Invalid product_name provided'
            msg += f"\nValid values: {', '.join(products_xw.keys())}"
            raise ValueError(msg)

        params = {
            'datasets': product_kw,
            'bbox': ','.join(map(str, bbox.bounds)),
            'outputFormat': 'JSON',
            'version': 1
        }

        r = requests.get(url, params=params)
        return r.json()
