import os

import requests
from dotenv import load_dotenv

from .base import DataSource, PolygonSource


class NationalParkBoundaries(PolygonSource):
    def __init__(self):
        super(NationalParkBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.url = 'https://opendata.arcgis.com/datasets/b1598d3df2c047ef88251016af5b0f1e_0.zip?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%22%3A102100%7D'
        self.filename = 'nationalpark.geojson'


class NationalParksAPI(DataSource):
    """
    Wrapper to access the National Parks API
    """
    def __init__(self):
        super(NationalParksAPI, self).__init__()

        self.raw_dir = self.data_dir / 'raw' / 'nps'
        self.save_dir = self.data_dir / 'attrs' / 'nps'
        self.save_dir.mkdir(parents=True, exist_ok=True)

        load_dotenv()
        self.api_key = os.getenv('NPS_API_KEY')
        assert self.api_key is not None, 'Missing nps.gov API Key'

        self.park_codes = [
            'SEKI',
            'DEPO',
            'LAVO',
            'MORA',
            'YOSE',
            'NOCA',
            'LACH',
            'CRLA',
        ]
        self.base_url = 'https://developer.nps.gov/api/v1'

    def download(self):
        """Download park metadata for each park
        """

        url = f'{self.base_url}/parks'
        params = {
            'fields': 'name,images,designation,description',
            'api_key': self.api_key
        }
        for park_code in self.park_codes:
            params['parkCode'] = park_code
            r = requests.get(url, params=params)
            # assert
            # r.url
            # r.json()
            #
            # break
        # curl -X GET "/parks?parkCode=SEKI&fields=images&api_key=L2KkzRsHg5wo3HHuLte4AhlZykoNnEhcEKWWQ9Ev" -H "accept: application/json"
        # Get
