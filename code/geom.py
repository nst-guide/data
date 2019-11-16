from functools import partial

import geopandas as gpd
import pint
import pyproj
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


def reproject(obj, from_epsg, to_epsg):
    project = partial(pyproj.transform, pyproj.Proj(init=from_epsg),
                      pyproj.Proj(init=to_epsg))

    return transform(project, obj)


def wgs_to_web_mercator(obj):
    return reproject(obj, WGS84, WEB_MERCATOR)


def web_mercator_to_wgs(obj):
    return reproject(obj, WEB_MERCATOR, WGS84)
