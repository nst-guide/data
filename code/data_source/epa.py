import os
from datetime import datetime, timedelta

import geojson
import requests
from fastkml import kml
from shapely.geometry import asShape, shape


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
            - bbox: Bounding box for API request. You can only do 5 requests per
                hour with your API key, so choose a large bounding box, i.e.
                probably entire US.
            - air_measure: either 'PM25', 'Combined', or 'Ozone'

        Returns:
            geojson.FeatureCollection
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

        # Send GET request
        r = requests.get(url, params=params)
        if r.status_code != 200:
            return None

        # Parse KML response
        geometries, properties = self.parse_kml(r.content)

        # Convert KML properties into rgb, aqi properties
        properties = self.parse_properties(properties)

        # Simplify geometries
        geometries = [g.simplify(0.001) for g in geometries]

        # Reduce coordinate precision
        # 5 digits is still around 1m precision
        # https://en.wikipedia.org/wiki/Decimal_degrees
        geometries = [round_geometry(geom=g, digits=5) for g in geometries]

        # Coerce to GeoJSON FeatureCollection
        features = [
            geojson.Feature(geometry=g, properties=p)
            for g, p in zip(geometries, properties)
        ]
        fc = geojson.FeatureCollection(features)
        return fc

    def parse_kml(self, content):
        """Parse KML response

        Not sure why, but must be _bytes_ not _text_.

        Args:
            - content: KML string

        Returns:
            [List[Polygon], List[dict]]

            - list of shapely geometries;
            - list of dicts containing properties from KML file
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

        return geometries, properties

    def parse_properties(self, properties):
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
            - properties: List[dict] of properties from KML file

        Returns:
            List[dict] with structure:
            {'aqi': AQI_LEVEL, 'rgb': 'r,g,b'}
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

        # Turn color property to rgb
        rgb_colors = [kmlcolor_to_rgb(p['color']) for p in properties]

        # Map using aqi_mapping
        aqi_values = [aqi_mapping[c] for c in rgb_colors]

        # Create properties dicts with only `aqi` and `rgb` keys
        return [{
            'aqi': aqi,
            'rgb': rgb
        } for aqi, rgb in zip(aqi_values, rgb_colors)]


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


def round_geometry(geom, digits):
    """Round coordinates of geometry to desired digits

    Args:
        - geom: geometry to round coordinates of
        - digits: number of decimal places to round

    Returns:
        geometry of same type as provided
    """
    gj = [geojson.Feature(geometry=geom)]
    truncated = list(coord_precision(gj, precision=digits))
    return shape(truncated[0].geometry)


def coord_precision(features, precision, validate=True):
    """Truncate precision of GeoJSON features

    Taken from geojson-precision:
    https://github.com/perrygeo/geojson-precision

    The MIT License (MIT)

    Copyright (c) 2016 Matthew Perry

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to
    deal in the Software without restriction, including without limitation the
    rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
    sell copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
    IN THE SOFTWARE.
    """
    for feature in features:
        coords = _set_precision(feature['geometry']['coordinates'], precision)
        feature['geometry']['coordinates'] = coords
        if validate:
            geom = asShape(feature['geometry'])
            geom.is_valid
        yield feature


def _set_precision(coords, precision):
    """Truncate precision of coordinates

    Taken from geojson-precision:
    https://github.com/perrygeo/geojson-precision

    The MIT License (MIT)

    Copyright (c) 2016 Matthew Perry

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to
    deal in the Software without restriction, including without limitation the
    rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
    sell copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
    IN THE SOFTWARE.
    """
    result = []
    try:
        return round(coords, int(precision))
    except TypeError:
        for coord in coords:
            result.append(_set_precision(coord, precision))
    return result
