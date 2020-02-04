from functools import partial
from math import sqrt
from typing import List, Tuple

import geojson
import geopandas as gpd
import pyproj
from geojson import Feature
from shapely.geometry import (
    GeometryCollection, MultiPolygon, Point, Polygon, asShape, box, mapping,
    shape)
from shapely.ops import transform

import pint

from .smallest_enclosing_circle import make_circle

ureg = pint.UnitRegistry()

WGS84 = 4326
WEB_MERCATOR = 3857
UTM10 = 6339
UTM11 = 6340
CA_ALBERS = 3488


def buffer(
        geometry, distance: float, unit: str, crs: int = 3488) -> gpd.GeoSeries:
    """Create buffer around geometry

    Args:
        geometry: geometry to take buffer around. Can be either GeoDataFrame or
            shapely geometry. Source geometry must be in epsg 4326
        distance: distance magnitude for buffer
        unit: units for buffer distance, one of:
            ['mile', 'mi', 'meter', 'm', 'kilometer', 'km']
        crs: local projected coordinate system to use for buffer calculations. I
            tend to use 3488 for the PCT: https://epsg.io/3488.

    Returns:
        If given GeoDataFrame:
            - GeoDataFrame with buffer polygon

        If given Shapely object:
            - Shapely polygon
    """
    # Reproject to projected coordinate system
    geometry = reproject(geometry, to_epsg=crs, from_epsg=4326)

    # Find buffer distance in meters
    unit_dict = {
        'mile': ureg.mile,
        'mi': ureg.mile,
        'meter': ureg.meter,
        'm': ureg.meter,
        'kilometer': ureg.kilometer,
        'km': ureg.kilometer,
    }
    pint_unit = unit_dict.get(unit)
    if pint_unit is None:
        raise ValueError(f'unit must be one of {list(unit_dict.keys())}')

    distance_m = (distance * pint_unit).to(ureg.meters).magnitude
    buffer = geometry.buffer(distance_m)

    # Reproject back to EPSG 4326 for saving
    buffer = reproject(buffer, to_epsg=4326, from_epsg=crs)
    return buffer


def round_geometry(geom, digits):
    """Round coordinates of geometry to desired digits

    Args:
        - geom: geometry to round coordinates of
        - digits: number of decimal places to round

    Returns:
        geometry of same type as provided
    """
    gj = [Feature(geometry=geom)]
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


def validate_geom_gdf(gdf):
    geom_col = gdf.geometry.name
    gdf[geom_col] = gdf.apply(lambda row: validate_geom(row.geometry), axis=1)
    return gdf


def validate_geom(geom):
    if geom.is_valid:
        return geom

    return geom.buffer(0)


def validate_geojson(gj):
    """Make sure all geometries in GeoJSON are valid

    Args:
        - gj: must be geojson object!
    """
    return geojson.utils.map_geometries(
        lambda g: mapping(validate_geom(shape(g))), gj)


def to_2d(obj):
    """Convert geometric object from 3D to 2D"""
    if isinstance(obj, gpd.GeoDataFrame):
        return _to_2d_gdf(obj)

    if isinstance(obj, gpd.GeoSeries):
        return _to_2d_gdf(obj)

    return transform(_to_2d_transform, obj)


def _to_2d_gdf(obj):
    # Get geometry column
    geometry = obj.geometry

    # Replace geometry column with 2D coords
    geometry_name = obj.geometry.name
    try:
        obj[geometry_name] = geometry.apply(
            lambda g: transform(_to_2d_transform, g))
    except TypeError:
        # Means geometry is already 2D
        pass

    return obj


def _to_2d_transform(x, y, z=None):
    return tuple(filter(None, [x, y]))


def reproject(geometry, to_epsg: int, from_epsg: int = None):
    """Reproject geometric object to new coordinate system

    Args:
        - geometry: either GeoDataFrame or shapely geometry
        - to_epsg: new crs, should be epsg integer
        - from_epsg: old crs, not necessary for gdf
    """
    if isinstance(geometry, gpd.GeoDataFrame):
        return geometry.to_crs(epsg=to_epsg)

    if isinstance(geometry, gpd.GeoSeries):
        return geometry.to_crs(epsg=to_epsg)

    if from_epsg is None:
        msg = 'from_epsg must be provided when geometry is not gdf'
        raise ValueError(msg)

    project = partial(
        pyproj.transform, pyproj.Proj(init=f'epsg:{from_epsg}'),
        pyproj.Proj(init=f'epsg:{to_epsg}'))

    return transform(project, geometry)


def find_circles_that_tile_polygon(polygon, radius,
                                   crs=3488) -> List[Tuple[Polygon, float]]:
    """
    Following this article [0], I'll split into smaller and smaller rectangles
    until each rectangle is small enough to be circumscribed within `radius`.

    [0]: https://snorfalorpagus.net/blog/2016/03/13/splitting-large-polygons-for-faster-intersections/

    Args:
        - polygon: polygon in WGS84
        - radius: max radius of circle in meters
        - crs: epsg code of projected coordinate system using meters

    Returns:
        - list of (circle Polygons, circle radius)
    """
    # Find box diameter for a square box circumscribed within a circle of given
    # radius
    box_diameter = (radius / sqrt(2)) * 2

    # First, reproject polygon so that I can work in meters
    polygon = reproject(polygon, WGS84, crs)

    # Split polygon into distinct pieces with max height or width `box_diameter`
    # These pieces tile the original geometry
    res = katana(polygon, threshold=box_diameter)

    # Get minimum bounding circles for pieces of geometry
    #
    # You _can't_ just find the centroid and the distance from the centroid
    # because the centroid is _not_ the point in the polygon closest from every
    # point on the exterior. Rather, it's the center of mass. You could imagine
    # a big circle of mass around (0, 0) with a very small sliver that extends
    # to (20000, 0). That sliver would have small mass, so the centroid would
    # still be near (0, 0), but wouldn't be the point with minimum distance to
    # the exterior.
    #
    # Instead, you need to get the _minimum bounding circle_, i.e. the smallest
    # circle that fully encloses your polygon.
    # Ref:
    # https://stackoverflow.com/a/41776277
    circles = [make_circle(g.exterior.coords) for g in res]
    points = [Point(x, y) for x, y, r in circles]
    radii = [x[2] for x in circles]

    # Reproject back to WGS84
    reprojected_points = [reproject(point, crs, WGS84) for point in points]
    return reprojected_points, radii


def katana(geometry, threshold, count=0):
    """Split a Polygon into parts across its shortest dimension

    Args:
        - geometry: _projected_ geometry to split
        - threshold: maximum width or height for each box

    Retrieved from:
    https://snorfalorpagus.net/blog/2016/03/13/splitting-large-polygons-for-faster-intersections/

    Copyright © 2016, Joshua Arnott

    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:

    1. Redistributions of source code must retain the above copyright notice,
        this list of conditions and the following disclaimer.
    2. Redistributions in binary form must reproduce the above copyright notice,
        this list of conditions and the following disclaimer in the
        documentation and/or other materials provided with the distribution.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS IS”
    AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
    IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
    ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
    LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
    CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
    SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
    INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
    CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
    ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
    POSSIBILITY OF SUCH DAMAGE.
    """
    bounds = geometry.bounds
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    if max(width, height) <= threshold or count == 250:
        # either the polygon is smaller than the threshold, or the maximum
        # number of recursions has been reached
        return [geometry]
    if height >= width:
        # split left to right
        a = box(bounds[0], bounds[1], bounds[2], bounds[1] + height / 2)
        b = box(bounds[0], bounds[1] + height / 2, bounds[2], bounds[3])
    else:
        # split top to bottom
        a = box(bounds[0], bounds[1], bounds[0] + width / 2, bounds[3])
        b = box(bounds[0] + width / 2, bounds[1], bounds[2], bounds[3])
    result = []
    for d in (
            a,
            b,
    ):
        c = geometry.intersection(d)
        if not isinstance(c, GeometryCollection):
            c = [c]
        for e in c:
            if isinstance(e, (Polygon, MultiPolygon)):
                result.extend(katana(e, threshold, count + 1))
    if count > 0:
        return result
    # convert multipart into singlepart
    final_result = []
    for g in result:
        if isinstance(g, MultiPolygon):
            final_result.extend(g)
        else:
            final_result.append(g)
    return final_result
