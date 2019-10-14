from functools import partial

import pyproj
from shapely.ops import transform

WGS = 'epsg:4326'
WEB_MERCATOR = 'epsg:3857'
UTM10 = 'epsg:6339'
UTM11 = 'epsg:6340'

def reproject(obj, from_epsg, to_epsg):
    project = partial(
        pyproj.transform,
        pyproj.Proj(init=from_epsg),
        pyproj.Proj(init=to_epsg))

    return transform(project, obj)


def wgs_to_web_mercator(obj):
    return reproject(obj, WGS, WEB_MERCATOR)

def web_mercator_to_wgs(obj):
    return reproject(obj, WEB_MERCATOR, WGS)
