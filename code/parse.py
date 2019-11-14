# Upload waypoints to Parse Server

import json
import os
from datetime import datetime
from typing import List, Optional

import geopandas as gpd
import requests
from dotenv import load_dotenv
from shapely.geometry import Point


def main():
    load_dotenv()
    app_id = os.getenv('PARSE_APP_ID')
    assert app_id is not None, 'app_id missing'
    master_key = os.getenv('PARSE_MASTER_KEY')
    assert master_key is not None, 'master_key missing'
    server_url = os.getenv('PARSE_SERVER_URL')
    assert server_url is not None, 'server_url missing'
    parse = Parse(app_id=app_id, server_url=server_url, master_key=master_key)


def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))


class Parse(object):
    """docstring for Parse"""
    def __init__(self,
                 app_id: str,
                 server_url: str,
                 master_key: str = None,
                 rest_key: str = None):
        """Wrapper for Parse HTTP API

        Args:
            app_id: Parse server Application Id
            server_url: Parse server URL
            master_key: Parse server master key
            rest_key: Parse server REST key
        """
        super(Parse, self).__init__()

        self.app_id = app_id
        self.master_key = master_key
        self.server_url = server_url
        self.rest_key = rest_key

        self.headers = {'X-Parse-Application-Id': self.app_id}
        if self.rest_key is not None:
            self.headers['X-Parse-REST-API-Key'] = self.rest_key
        if self.master_key is not None:
            self.headers['X-Parse-Master-Key'] = self.master_key

    def query(self, class_name: str, query: Optional[dict] = None) -> dict:
        """
        Right now this only supports basic queries
        https://docs.parseplatform.org/rest/guide/#queries

        Args:
            class_name: name of class to put in URL
            query: dictionary of query. Not sure if this actually works
        """
        url = f'{self.server_url}/classes/{class_name}'
        data = None
        if query is not None:
            s = json.dumps(query, separators=(',', ':'))
            data = f'where={s}'
        r = requests.get(url, headers=self.headers, data=data)
        return r.json()

    def encode_geopoint(self, lon: float, lat: float) -> dict:
        return {'__type': 'GeoPoint', 'latitude': lat, 'longitude': lon}

    def encode_date(self, date: datetime) -> dict:
        """
        NOTE: for now this assumes that the date is already in UTC
        """
        return {
            '__type': 'Date',
            'iso': date.isoformat(timespec='milliseconds') + 'Z'
        }

    def encode_pointer(self, class_name: str, object_id: str) -> dict:
        return {
            '__type': 'Pointer',
            'className': class_name,
            'objectId': object_id
        }

    def encode_relation(self, class_name: str):
        return {'__type': 'Relation', 'className': 'GameScore'}

    def upload_gdf(self,
                   gdf: gpd.GeoDataFrame,
                   class_name: str,
                   upload_altitude: bool = True):
        """Upload GeoDataFrame to Parse

        Args:
            gdf: GeoDataFrame with data to upload
            class_name: name of class to upload data to in Parse
            upload_altitude: whether to upload altitude as an attribute for Point Z geometries. Uploaded as "alt".
        """
        url = f'{self.server_url}/classes/{class_name}'
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'

        json_data = []
        geom_name = gdf.geometry.name
        columns = [x for x in gdf.columns if x != geom_column_name]
        for row in gdf.itertuples():
            d = {}

            # Make sure that type of geometry is point
            geom = getattr(row, geom_name)
            assert isinstance(geom, Point), 'Geometry not of type Point'

            # is it a 2D or 3D point?
            coords = list(geom.coords)[0]
            lon = coords[0]
            lat = coords[1]
            alt = coords[2] if len(coords) == 3 else None

            d[geom_name] = self.encode_geopoint(lon=lon, lat=lat)
            if (alt is not None) and upload_altitude:
                d['alt'] = alt

            for column in columns:
                d[column] = getattr(row, column)

            json_data.append(d)

        for group in chunker(json_data, 50):
            self.upload_batch(data=group, class_name=class_name)

    def upload_batch(self, data: List[dict], class_name: str):
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'

        body = [{
            'method': 'POST',
            'path': f'/parse/classes/{class_name}',
            'body': x
        } for x in data]
        body = {'requests': body}

        url = f'{self.server_url}/batch'
        r = requests.post(url, data=json.dumps(body), headers=headers)
        return r.json()

    def upload_file(self, data, fname: str, content_type: str):
        """Upload file

        TODO: urlencode/base64 encode data?
        """
        raise NotImplementedError('figure out data encoding')

        headers = self.headers.copy()
        headers['Content-Type'] = content_type
        url = f'{self.server_url}/files/{fname}'
        r = requests.post(url, data=data, headers=headers)
        return r.json()


if __name__ == '__main__':
    main()
