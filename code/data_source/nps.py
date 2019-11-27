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

        self.base_url = 'https://developer.nps.gov/api/v1'

    def query(self, park_codes, endpoint, fields=None):
        """Get information from NPS API

        Args:
            - park_codes: Park identifier, usually four letters, i.e. YOSE
            - endpoint: either
            - fields: fields to return
        """
        if not isinstance(park_codes, list):
            raise TypeError('park_codes must be a list of str')
        if fields is not None:
            if not isinstance(fields, list):
                raise TypeError('fields must be None or a list of str')

        if fields is None and endpoint == 'parks':
            fields = ['images']

        endpoint = endpoint.strip('/')
        url = f'{self.base_url}/{endpoint}'
        params = {
            'api_key': self.api_key,
            'parkCode': ','.join(park_codes),
            'fields': fields,
            'limit': 500,
        }
        headers = {'accept': 'application/json'}
        r = requests.get(url, params=params, headers=headers)

        # Make a dict of list of dicts, where the top-level key is the park code
        dict_data = {}
        for d in r.json()['data']:
            park_code = d['parkCode'].lower()
            dict_data[park_code] = dict_data.get(park_code, [])
            dict_data[park_code].append(d)

        return dict_data
