from functools import partial

import geojson
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

def osm_poly_to_geojson(lines):
    lines = [line.rstrip() for line in lines]
    name = lines[0]

    section_starts = [ind for ind, line in enumerate(lines) if line[:3] not in ['   ', 'END']]
    section_ends = [ind for ind, line in enumerate(lines) if line[:3] == 'END']

    features = []
    for start, end in zip(section_starts, section_ends):
        part = lines[start:end]
        section_name = part[0]
        coords = [line.split() for line in part[1:]]

        # Convert str to float
        # the float() function handles the scientific notation
        coords = [(float(coord[0]), float(coord[1])) for coord in coords]

        polygon = geojson.Polygon(coordinates=coords)
        feature = geojson.Feature(geometry=polygon, properties={'name': section_name})
        features.append(feature)

    feature_collection = geojson.FeatureCollection(features)
    return feature_collection

def coords_to_osm_poly(coords):
    lines = [
        'poly_name',
        'first_area',
    ]
    for coord in coords:
        lines.append(f'    {coord[0]}    {coord[1]}')
    lines.append('END')
    lines.append('END')
    return '\n'.join(lines)
