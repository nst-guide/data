import os
from io import BytesIO
from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd
from dotenv import load_dotenv
from shapely.geometry import Point

import geom
from base import DataSource
from halfmile import Halfmile


class RecreationGov(DataSource):
    def __init__(self):
        super(RecreationGov, self).__init__()

        self.raw_dir = self.data_dir / 'raw' / 'recreationgov'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        load_dotenv()
        self.api_key = os.getenv('RIDB_API_KEY')
        assert self.api_key is not None, 'Missing Recreation.gov API Key'

    def download(self, overwrite=False):
        # To download all the RIDB recreation area, facility, and site level
        # data in CSV or JSON format, please select the link below. Updated
        # Daily.
        url = 'https://ridb.recreation.gov/downloads/RIDBFullExport_V1_CSV.zip'
        local_path = self.raw_dir / Path(url).name
        if overwrite or (not local_path.exists()):
            urlretrieve(url, local_path)

    def get_campsites_near_trail(self, trail):
        section_name, trail = next(Halfmile().trail_iter())
        trail_buf = geom.buffer(trail, distance=2, unit='mile')
        trail_buf = gpd.GeoDataFrame(geometry=trail_buf)
        buf = geom.buffer(trail, distance=2, unit='mile').unary_union

        local_path = self.raw_dir / 'RIDBFullExport_V1_CSV.zip'
        z = ZipFile(local_path)
        z.namelist()
        df = pd.read_csv(BytesIO(z.read('Facilities_API_v1.csv')))
        gdf = gpd.GeoDataFrame(
            df,
            geometry=df.apply(
                lambda row: Point(
                    row['FacilityLongitude'], row['FacilityLatitude']),
                axis=1))
