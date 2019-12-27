from datetime import datetime

import fiona
import geojson
import pyproj
import requests
from shapely.geometry import asShape, box, shape
from shapely.ops import transform

# Bounding box used to filter wildfires
BBOX = (-125.64, 31.35, -114.02, 49.33)


class NIFCCurrent:
    def __init__(self):
        super(NIFCCurrent, self).__init__()

    def current(self):
        url = 'https://opendata.arcgis.com/datasets/5da472c6d27b4b67970acc7b5044c862_0.zip'
        r = requests.get(url)

        with fiona.BytesCollection(r.content,
                                   layer='Wildfire_Perimeters') as col:
            gj = self.parse_features(col)

        return gj


    def parse_features(self, col):
        """
        """
        geometries = []
        properties = []
        for feature in col:
            # Append shapely object to geometries
            # Note that occasionally rows have null geometry
            try:
                geometries.append(shape(feature['geometry']))
            except:
                continue

            # Append properties to properties
            properties.append(feature['properties'])

        msg = 'geometries and properties have different lengths'
        assert len(geometries) == len(properties), msg

        # Reproject to WGS84
        if col.crs != {'init': 'epsg:4326'}:
            project = pyproj.Transformer.from_proj(
                pyproj.Proj(col.crs), pyproj.Proj(init='epsg:4326'))
            geometries = [transform(project.transform, g) for g in geometries]

        # Keep features in BBOX
        # First find indices of geometries that are in bounding box, then keep
        # the geometries and properties with those indices
        bbox = box(*BBOX)
        indices = [
            ind for ind, g in enumerate(geometries) if g.intersects(bbox)
        ]
        geometries = [g for ind, g in enumerate(geometries) if ind in indices]
        properties = [p for ind, p in enumerate(properties) if ind in indices]

        # Simplify geometries
        geometries = [g.simplify(0.001) for g in geometries]

        # Reduce coordinate precision
        # 5 digits is still around 1m precision
        # https://en.wikipedia.org/wiki/Decimal_degrees
        geometries = [round_geometry(geom=g, digits=5) for g in geometries]

        # Keep latest geometry for each fire id
        # Some fires have more than one geometry in the current database. Only
        # keep the most recent date
        # latest has form {IRWINID: {'DateCurren', ind}}
        latest = {}
        for ind, p in enumerate(properties):
            date = p.get('DateCurren')

            # If date doesn't exist, leave this out of the dataset
            if date is None:
                continue

            # Replace Zulu time zone if it exists with +0
            date = date.replace("Z", "+00:00")

            # Parse with datetime.fromisoformat
            # Note this is Python 3.7+
            date = datetime.fromisoformat(date)

            irwinid = p.get('IRWINID')
            if irwinid is None:
                continue

            existing_item = latest.get(irwinid)
            if existing_item is None:
                latest[irwinid] = {'DateCurren': date, 'index': ind}
                continue

            # Fire irwinid already exists in `latest` dict
            # If current date is later, replace
            existing_date = existing_item['DateCurren']
            if date > existing_date:
                latest[irwinid] = {'DateCurren': date, 'index': ind}
                continue

        # Keep only the indices that correspond with the most recent rows
        indices = [l['index'] for l in latest.values()]
        geometries = [g for ind, g in enumerate(geometries) if ind in indices]
        properties = [p for ind, p in enumerate(properties) if ind in indices]

        # Keep only necessary keys from properties
        keys = ['IncidentNa', 'GISAcres', 'DateCurren']
        properties = [{key: p[key]
                       for key in keys
                       if p.get(key) is not None}
                      for p in properties]

        # Finally, create GeoJSON from geometries and properties
        features = [
            geojson.Feature(geometry=g, properties=p)
            for g, p in zip(geometries, properties)
        ]
        fc = geojson.FeatureCollection(features)

        return fc


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
