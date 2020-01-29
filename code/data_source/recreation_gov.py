import os
from io import BytesIO
from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd
import requests
from dotenv import load_dotenv
from shapely.geometry import Point

from .base import DataSource
from .halfmile import Halfmile

try:
    import geom
except ModuleNotFoundError:
    # Development in IPython
    import sys
    sys.path.append('../')
    import geom

# FORESTORGC, FORESTNAME, RecAreaID
nf_rec_area_id_xw = [
    ('0618', 'Willamette National Forest', '1114'),
    ('0606', 'Mt. Hood National Forest', '1106'),
    ('0519', 'Lake Tahoe Basin Management Unit', '2025'),
    ('0603', 'Gifford Pinchot National Forest', '16684'),
    ('0515', 'Sierra National Forest', '1074'),
    ('0516', 'Stanislaus National Forest', '1076'),
    ('0502', 'Cleveland National Forest', '1062'),
    ('0514', 'Shasta-Trinity National Forest', '1073'),
    ('0512', 'San Bernardino National Forest', '1071'),
    ('0511', 'Plumas National Forest', '1070'),
    ('0506', 'Lassen National Forest', '1066'),
    ('0501', 'Angeles National Forest', '1061'),
    ('0505', 'Klamath National Forest', '1065'),
    ('0513', 'Sequoia National Forest', '1072'),
    ('0504', 'Inyo National Forest', '1064'),
    ('0517', 'Tahoe National Forest', '1077'),
    ('0503', 'Eldorado National Forest', '1063'),
    ('0622', 'Columbia River Gorge National Scenic Area', '1102'),
    ('0602', 'Fremont-Winema National Forest', '1104'),
    ('0617', 'Okanogan-Wenatchee National Forest', '16822'),
    ('0610', 'Rogue River-Siskiyou National Forests', '16682'),
    ('0605', 'Mt. Baker-Snoqualmie National Forest', '1118'),
    ('0601', 'Deschutes National Forest', '14492'),
    ('0615', 'Umpqua National Forest', '1112'),
]
wild_rec_area_id_xw = [
    ('Domeland Wilderness', '14779'),
    ('Kiavah Wilderness', '13088'),
    ('San Gorgonio Wilderness', '13237'),
    ('Soda Mountain Wilderness', '13481'),
    ('Chimney Peak Wilderness', '13367'),
]


class RecreationGov(DataSource):
    def __init__(self):
        super(RecreationGov, self).__init__()

        self.raw_dir = self.data_dir / 'raw' / 'recreationgov'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        load_dotenv()
        self.api_key = os.getenv('RIDB_API_KEY')
        assert self.api_key is not None, 'Missing Recreation.gov API Key'

        self.base_url = 'https://ridb.recreation.gov/api/v1'

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

    def query(self, query, endpoint, limit=2, full=True):
        """Get information from Recreation.gov API

        Args:
            - query: Park identifier, usually four letters, i.e. YOSE
            - endpoint: either
            - limit: max number of results
            - full: whether to return "full" results or not. Full results includes
        """
        endpoint = endpoint.strip('/')
        url = f'{self.base_url}/{endpoint}'
        params = {
            'query': query,
            'limit': limit,
            'full': full,
        }
        headers = {'accept': 'application/json', 'apikey': self.api_key}
        r = requests.get(url, params=params, headers=headers)
        return r.json()

    def official_link(self, rec_area_id):
        """Get official area link given rec area ID
        """
        endpoint = f'recareas/{rec_area_id}/links'
        url = f'{self.base_url}/{endpoint}'
        headers = {'accept': 'application/json', 'apikey': self.api_key}
        r = requests.get(url, headers=headers)
        d = r.json()

        # Select the official web site link
        links = [
            x for x in d['RECDATA'] if x['LinkType'] == 'Official Web Site'
        ]
        assert len(links) == 1, 'Not 1 official website'
        link = links[0]

        return link['URL']

    def image(self, rec_area_id):
        """Get best image from RIDB API given rec area ID
        """
        endpoint = f'recareas/{rec_area_id}/media'
        url = f'{self.base_url}/{endpoint}'
        headers = {'accept': 'application/json', 'apikey': self.api_key}
        r = requests.get(url, headers=headers)
        d = r.json()

        if d['METADATA']['RESULTS']['TOTAL_COUNT'] == 0:
            return None

        # Select the official web site link
        preview_images = [
            x for x in d['RECDATA'] if x['IsPreview'] == True
        ]
        assert len(preview_images) == 1, 'Not 1 preview image'
        image = preview_images[0]

        # Return dict with only specified keys, and lower case
        keep_keys = ['Title', 'Description', 'URL', 'Credits']
        return {k.lower(): v for k, v in image.items() if k in keep_keys}

    def facilities(self, rec_area_id):
        """Get facilities from RIDB API given rec area ID
        """
        endpoint = f'recareas/{rec_area_id}/facilities'
        url = f'{self.base_url}/{endpoint}'
        headers = {'accept': 'application/json', 'apikey': self.api_key}
        r = requests.get(url, headers=headers)
        return r.json()
