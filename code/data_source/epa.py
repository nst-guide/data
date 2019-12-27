import os
from datetime import datetime, timedelta

import geopandas as gpd
import requests
from fastkml import kml


class EPAAirNow:
    """Retrieve air quality contours from EPA AirNow API

    This assumes that EPA_AIRNOW_API_KEY is already in the environment. If
    needed, call `dotenv.load_dotenv` _before_ instantiating this class. This is
    so that this file does not have a dependency on dotenv, and can be copied to
    AWS Lambda more easily.
    """
    def __init__(self):
        super(EPAAirNow, self).__init__()

        self.api_key = os.getenv('EPA_AIRNOW_API_KEY')
        assert self.api_key is not None, 'EPA AIRNOW key missing'

    def current_air_quality(self, bbox=None, air_measure='PM25'):
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

        # This is a huge bounding box for all 50 US States, from here:
        # https://gist.github.com/graydon/11198540
        if bbox is None:
            bbox = (-171.791110603, 18.91619, -66.96466, 71.3577635769)
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
        fc = self.parse_kml(r.content)
        return self.features_to_gdf(fc)

    def parse_kml(self, content):
        """Parse KML response

        Not sure why, but must be _bytes_ not _text_.

        Args:
            - content: KML string

        Returns:
            GeoDataFrame with columns:
            - style_id
            - color
            - fill
            - outline
            - geometry
        """
        k = kml.KML()
        k.from_string(content)

        # Loop over kml objects and create a feature collection
        geometries = []
        properties = []
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

                    props = {'style_id': style_id}
                    props.update(style)

                    geometries.append(placemark.geometry)
                    properties.append(props)

        return gpd.GeoDataFrame(properties, geometry=geometries)

    def parse_color(self, gdf):
        """Parse KML colors and convert to AQI levels

        EPA AirNow Color scheme:

        | AQI                            | Color  | RGB        |
        |--------------------------------|--------|------------|
        | Good                           | Green  | 0,228,0    |
        | Moderate                       | Yellow | 255,255,0  |
        | Unhealthy for Sensitive Groups | Orange | 255,126,0  |
        | Unhealthy                      | Red    | 255,0,0    |
        | Very Unhealthy                 | Purple | 143,63,151 |
        | Hazardous                      | Maroon | 126,0,35   |

        Ref:
        https://docs.airnowapi.org/docs/AirNowMappingFactSheet.pdf?docs%2FAirNowMappingFactSheet.pdf=

        Args:
            - gdf: GeoDataFrame

        Returns:
            GeoDataFrame with columns:
            - geometry
            - rgb (string of format '255,255,0')
            - aqi (one of good, moderate, usg, unhealthy, very_unhealthy, and
              hazardous)
        """
        # RGB to AQI level
        # https://docs.airnowapi.org/docs/AirNowMappingFactSheet.pdf?
        # docs%2FAirNowMappingFactSheet.pdf=
        aqi_mapping = {
            '0,228,0': 'good',
            '255,255,0': 'moderate',
            '255,126,0': 'usg',
            '255,0,0': 'unhealthy',
            '143,63,151': 'very_unhealthy',
            '126,0,35': 'hazardous',
        }

        # Turn color column to rgb numbers
        gdf['rgb'] = gdf['color'].apply(lambda s: kmlcolor_to_rgb(s))

        # Run on aqi mapping
        gdf['aqi'] = gdf['rgb'].map(aqi_mapping)
        gdf = gdf[['geometry', 'rgb', 'aqi']]

        return gdf


def kmlcolor_to_rgb(s):
    """
    KML colors are in aabbggrr order!! So if the color is FF00FFFF then:
    - opacity FF (255)
    - blue 00 (0)
    - green FF (255)
    - red FF (255)

    Ref: https://stackoverflow.com/a/13036015

    Args:
        - s: kml color string
    """
    s = s.upper()
    b = int(s[2:4], 16)
    g = int(s[4:6], 16)
    r = int(s[6:8], 16)
    return f'{r},{g},{b}'
