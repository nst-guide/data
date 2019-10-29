# Tools to help make iteration and prototyping fast

import json
import os
import webbrowser
from collections.abc import Iterable
from pathlib import Path

import dotenv
import geojson
import shapely.geometry
from keplergl import KeplerGl
from shapely.geometry import mapping


class Visualize:
    """Quickly visualize data in browser over Mapbox tiles with the help of the AMAZING kepler.gl.
    """
    def __init__(self, data=None):
        """Visualize data using kepler.gl

        Args:
            data Optional[Union[List[]]]:
                either None, a List of data objects, or a single data object. If
                data is not None, then Visualize(data) will perform all steps,
                including rendering and opening a browser.
        """
        super(Visualize, self).__init__()

        dotenv.load_dotenv()
        self.MAPBOX_API_KEY = os.getenv('MAPBOX_GL_WEB_TESTING')
        assert self.MAPBOX_API_KEY is not None, ''

        self.map = KeplerGl(config=self.config)

        if data is not None:
            if isinstance(data, Iterable):
                name_id = 0
                for item in data:
                    self.add_data(item, f'data_{name_id}')
                    name_id += 1
            else:
                self.add_data(item, f'data_0')

            self.render()

    @property
    def config(self):
        """Load kepler.gl config and insert Mapbox API Key"""

        with open('keplergl_config.json') as f:
            keplergl_config = json.load(f)

        # Replace redacted API key with actual API key
        keplergl_config['config']['config']['mapStyle']['mapStyles'][
            'aobtafp']['accessToken'] = self.MAPBOX_API_KEY
        keplergl_config['config']['config']['mapStyle']['mapStyles'][
            'aobtafp']['icon'] = keplergl_config['config']['config'][
                'mapStyle']['mapStyles']['aobtafp']['icon'].replace(
                    'access_token=redacted',
                    f'access_token={self.MAPBOX_API_KEY}')

        # Remove map state in the hope that it'll auto-center based on data
        keplergl_config['config']['config'].pop('mapState')
        return keplergl_config['config']

    def add_data(self, data, name):
        """Add data to kepler map

        Data should be either GeoJSON or GeoDataFrame. Kepler isn't aware of the
        geojson or shapely package, so if I supply an object from one of these
        libraries, first convert it to a GeoJSON dict.
        """
        shapely_geojson_classes = [
            shapely.geometry.LineString,
            shapely.geometry.LinearRing,
            shapely.geometry.MultiLineString,
            shapely.geometry.MultiPoint,
            shapely.geometry.MultiPolygon,
            shapely.geometry.Point,
            shapely.geometry.Polygon,
            geojson.Feature,
            geojson.FeatureCollection,
            geojson.GeoJSON,
            geojson.GeoJSONEncoder,
            geojson.GeometryCollection,
            geojson.LineString,
            geojson.MultiLineString,
            geojson.MultiPoint,
            geojson.MultiPolygon,
            geojson.Point,
            geojson.Polygon,
        ]
        if any(isinstance(data, c) for c in shapely_geojson_classes):
            data = dict(mapping(data))

        self.map.add_data(data=data, name=name)

    def render(self, open_chrome=True):
        """Export kepler.gl map to HTML file and open in Chrome
        """
        html_path = 'demo.html'
        self.map.save_to_html(file_name=html_path)

        # Open Chrome to saved page
        # Note, path to Chrome executable likely different on Windows/Linux
        # 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe %s'
        # chrome_path = '/usr/bin/google-chrome %s'
        chrome_bin = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        if Path(chrome_bin).exists() and open_chrome:
            # Add \ to spaces
            s = 'open -a ' + chrome_bin.replace(' ', '\ ') + ' %s'
            webbrowser.get(s).open(html_path)
        else:
            print('Warning: Chrome binary not found; path ')
