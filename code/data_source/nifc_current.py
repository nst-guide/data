"""
nifc_current.py: Retrieve current wildfire perimeters from the National
Interagency Fire Center.

This script is designed to be run on AWS Lambda. As such, dependencies are kept
to a minimum. Essentially no more dependencies can be added. Special work has
been made to avoid both GeoPandas and Fiona.
"""

from datetime import datetime
from io import BytesIO
from zipfile import ZipFile

import geojson
import pyproj
import requests
import shapefile
from shapely.geometry import asShape, box, shape
from shapely.ops import transform

# Bounding box used to filter wildfires
BBOX = (-125.64, 31.35, -114.02, 49.33)


class NIFCCurrent:
    def __init__(self):
        super(NIFCCurrent, self).__init__()

    def geojson(self):
        """Retrieve NIFC Shapefile and convert into well-formatted GeoJSON"""
        url = 'https://opendata.arcgis.com/datasets/5da472c6d27b4b67970acc7b5044c862_0.zip'
        r = requests.get(url)
        buf = BytesIO(r.content)

        geometries, properties, prj = self.load_shapefile(buf)
        gj = self.parse_features(geometries, properties, prj)
        return gj

    def load_shapefile(self, buf):
        """Load shapefile from BytesIO buffer using pyshp

        Args:
            - buf (BytesIO): a buffer containing a Zip archive of a Shapefile.
              The names within the Shapefile are expected to be
              `Wildfire_Perimeters.*`. At least the `.shp`, `.dbf`, and `.shx`
              files are expected to exist.

        Returns:
            (List[shapely geometry], List[dict], pyproj.Proj)

            - a list of Shapely geometries
            - a list of dictionary records that correspond to the geometries (in
              the same order)
            - the projection of the data as a pyproj.Proj instance
        """
        with ZipFile(buf) as zf:
            shp = BytesIO(zf.read('Wildfire_Perimeters.shp'))
            dbf = BytesIO(zf.read('Wildfire_Perimeters.dbf'))
            shx = BytesIO(zf.read('Wildfire_Perimeters.shx'))

            # The .prj file is the projection encoded as Well-Known Text
            prj = pyproj.Proj(
                zf.read('Wildfire_Perimeters.prj').decode('utf-8'))

            with shapefile.Reader(shp=shp, dbf=dbf, shx=shx) as r:
                geometries, properties = self._read_shape_records(r)
                return geometries, properties, prj

    def _read_shape_records(self, r):
        """Read Shapefile records into list of Shapely geometries and dicts

        Args:
            - r (shapefile.Reader): an open pyshp reader object

        Returns:
            (List[shapely geometry], List[dict])

            - a list of Shapely geometries
            - a list of dictionary records that correspond to the geometries (in
              the same order)
        """
        # Load shapes and records at the same time
        # Returns a list of custom shapeRecord objects
        shape_records = r.shapeRecords()

        # Note that pyshp raises an Exception when coercing to GeoJSON if the
        # geometry is NULL. So pass the records that are null, and coerce the
        # others.
        geometries = []
        properties = []
        for shape_record in shape_records:
            if shape_record.shape.shapeTypeName == 'NULL':
                continue

            # __geo_interface__ seems to be a standard way to coerce to GeoJSON
            # It doesn't look like there's another more-public method to do this
            geometries.append(shape_record.shape.__geo_interface__)
            properties.append(shape_record.record.as_dict())

        msg = 'geometries and properties have different lengths'
        assert len(geometries) == len(properties), msg

        # Coerce geometries to shapely objects
        geometries = [shape(g) for g in geometries]

        return geometries, properties

    def parse_features(self, geometries, properties, prj):
        """Parse and simplify features

        Create cleaned, simplified geometries with only the minimum number of
        properties necessary.

        Args:
            - geometries (List[shapely geometry]): a list of Shapely geometries
            - properties (List[dict]): a list of dictionary records that
              correspond to the geometries (in the same order)
            - prj (pyproj.Proj): the projection of the input data

        Returns:
            (geojson.FeatureCollection)
        """
        # Reproject to WGS84 if necessary
        if prj != pyproj.Proj(init='epsg:4326'):
            project = pyproj.Transformer.from_proj(
                prj, pyproj.Proj(init='epsg:4326'))
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
