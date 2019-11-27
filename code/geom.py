from functools import partial
from math import sqrt
from typing import List, Tuple

import geopandas as gpd
import pint
import pyproj
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import transform

ureg = pint.UnitRegistry()

WGS84 = 'epsg:4326'
WEB_MERCATOR = 'epsg:3857'
UTM10 = 'epsg:6339'
UTM11 = 'epsg:6340'
CA_ALBERS = 'epsg:3488'


def buffer(gdf: gpd.GeoDataFrame, distance: float, unit: str) -> gpd.GeoSeries:
    """Create buffer around GeoDataFrame

    Args:
        gdf: dataframe with geometry to take buffer around
        distance: distance for buffer
        unit: units for buffer distance, either ['mile', 'meter', 'kilometer']

    Returns:
        GeoDataFrame with buffer polygon
    """

    # Reproject to EPSG 3488 (meter accuracy)
    # https://epsg.io/3488
    gdf = gdf.to_crs(epsg=3488)

    # Find buffer distance in meters
    unit_dict = {
        'mile': ureg.mile,
        'meter': ureg.meter,
        'kilometer': ureg.kilometer,
    }
    pint_unit = unit_dict.get(unit)
    if pint_unit is None:
        raise ValueError(f'unit must be one of {list(unit_dict.keys())}')

    distance_m = (distance * pint_unit).to(ureg.meters).magnitude
    buffer = gdf.buffer(distance_m)

    # Reproject back to EPSG 4326 for saving
    buffer = buffer.to_crs(epsg=4326)

    return buffer


def validate_geom_gdf(gdf):
    geom_col = gdf.geometry.name
    gdf[geom_col] = gdf.apply(lambda row: validate_geom(row.geometry), axis=1)
    return gdf


def validate_geom(geom):
    if geom.is_valid:
        return geom

    return geom.buffer(0)


def to_2d(obj):
    """Convert geometric object from 3D to 2D"""
    if isinstance(obj, gpd.GeoDataFrame):
        return _to_2d_gdf(obj)

    try:
        return transform(_to_2d_transform, obj)
    except TypeError:
        # Means already 2D
        return obj


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


def _to_2d_transform(x, y, z):
    return tuple(filter(None, [x, y]))


def reproject_gdf(gdf, from_epsg, to_epsg):
    gdf[gdf.geometry.name] = gdf.apply(
        lambda row: reproject(
            row.geometry, from_epsg=from_epsg, to_epsg=to_epsg),
        axis=1)
    return gdf


def reproject(obj, from_epsg, to_epsg):
    project = partial(
        pyproj.transform, pyproj.Proj(init=from_epsg),
        pyproj.Proj(init=to_epsg))

    return transform(project, obj)


def wgs_to_web_mercator(obj):
    return reproject(obj, WGS84, WEB_MERCATOR)


def web_mercator_to_wgs(obj):
    return reproject(obj, WEB_MERCATOR, WGS84)


def find_circles_that_tile_polygon(polygon,
                                   radius) -> List[Tuple[Polygon, float]]:
    """
    Following this article [0], I'll split into smaller and smaller rectangles
    until each rectangle is small enough to be circumscribed within `radius`.

    [0]: https://snorfalorpagus.net/blog/2016/03/13/splitting-large-polygons-for-faster-intersections/

    Args:
        - polygon: polygon in WGS84
        - radius: radius in meters

    Returns:
        - list of (circle Polygons, circle radius)
    """
    # Find box radius (for a square box)
    box_diameter = (radius / sqrt(2)) * 2

    # First, reproject polygon so that I can work in meters
    polygon = reproject(polygon, WGS84, CA_ALBERS)

    # Split polygon
    res = katana(polygon, threshold=box_diameter)

    # For each polygon, find the centroid and then find the max distance from
    # the centroid back to the polygon
    circles = []
    distances = []
    for poly in res:
        centroid = poly.centroid
        max_dist = centroid.hausdorff_distance(poly)
        circle = centroid.buffer(max_dist)
        circles.append(circle)
        distances.append(max_dist)

    # Reproject back to WGS84
    reprojected_circles = [
        reproject(circle, CA_ALBERS, WGS84) for circle in circles
    ]
    return zip(reprojected_circles, distances)


def katana(geometry, threshold, count=0):
    """Split a Polygon into two parts across it's shortest dimension

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
