import os
from datetime import datetime, timedelta

import geojson
import requests
from dotenv import load_dotenv
from fastkml import kml

from base import DataSource


class EPAAirNow(DataSource):
    def __init__(self):
        super(EPAAirNow, self).__init__()

        load_dotenv()
        self.api_key = os.getenv('EPA_AIRNOW_API_KEY')
        assert self.api_key is not None, 'EPA AIRNOW key missing'

    def download(self, bbox=None, air_measure='PM25'):
        """Get current air pollution conditions from EPA AirNow

        Args:
            bbox: Bounding box for API request. You can only do 5 requests per
                hour with your API key, so choose a large bounding box, i.e.
                probably entire US.
            air_measure: either 'PM25', 'Combined', or 'Ozone'
        """
        # Date string (yyyy-mm-ddTHH)
        # January 1, 2012 at 1PM would be sent as: 2012-01-01T13
        # NOTE: they're generally a few hours behind, now - 3 hours should be
        # good generally
        time = datetime.utcnow()
        fmt = '%Y-%m-%dT%H'
        time_str = (time - timedelta(hours=3)).strftime(fmt)

        # TODO: Fix this bbox. Right now it's only a part of central CA
        if bbox is None:
            bbox = (-121.923904, 36.903504, -117.924881, 40.268781)
        bbox_str = [str(x) for x in bbox]

        # You can choose between just PM2.5, Ozone, and Combined
        air_measure_valid_values = ['PM25', 'Combined', 'Ozone']
        msg = 'air_measure must be one of {air_measure_valid_values}'
        assert air_measure in air_measure_valid_values, msg
        url = f'http://www.airnowapi.org/aq/kml/{air_measure}/'
        params = {
            'DATE': time_str,
            'BBOX': ','.join(bbox_str),
            'API_KEY': self.api_key,
            'SRS': 'EPSG:4326'
        }
        r = requests.get(url, params=params)
        k = kml.KML()
        k.from_string(r.content)

        featurecollection = []
        for document in k.features():
            all_styles = {}
            styles = list(document.styles())
            for style in styles:
                style_id = style.id
                polystyle = list(style.styles())[0]
                d = {
                    'color': polystyle.color,
                    'fill': polystyle.fill,
                    'outline': polystyle.outline
                }
                all_styles[style_id] = d

            for folder in document.features():
                for placemark in folder.features():
                    style_id = placemark.styleUrl.replace('#', '')
                    style = all_styles.get(style_id)

                    properties = {'style_id': style_id}
                    properties.update(style)

                    json_feature = geojson.Feature(
                        geometry=placemark.geometry, properties=properties)
                    featurecollection.append(json_feature)

        return geojson.FeatureCollection(features=featurecollection)
