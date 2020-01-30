import click
import geojson
from shapely.algorithms.polylabel import polylabel as polylabel_fn
from shapely.geometry import shape

from geom import validate_geojson
from copy import deepcopy


@click.command()
@click.argument(
    'file',
    required=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True))
def polylabel(file):
    """Create point labels for polygon features

    Adds the 'rank' property, which is the percentage of the total area of a
    multipolygon that an inner polygon takes up.
    """
    with open(file) as f:
        gj = geojson.load(f)

    if gj['type'] != 'FeatureCollection':
        raise ValueError('GeoJSON must be FeatureCollection')

    # For every geometry, make sure it is valid. If not, run buffer(0)
    gj = validate_geojson(gj)

    polylabel_features = []
    for feature in gj['features']:
        props = feature['properties']
        geometry = shape(feature['geometry'])

        if geometry.type == 'Polygon':
            label_props = deepcopy(props)
            label_props['rank'] = 1
            label_geometry = polylabel_fn(geometry, tolerance=0.01)
            f = geojson.Feature(geometry=label_geometry, properties=label_props)
            polylabel_features.append(f)
            continue
        elif geometry.type == 'MultiPolygon':
            total_area = sum(g.area for g in geometry)
            for polygon in geometry:
                label_props = deepcopy(props)
                label_props['rank'] = polygon.area / total_area
                label_geometry = polylabel_fn(polygon, tolerance=0.01)
                f = geojson.Feature(
                    geometry=label_geometry, properties=label_props)
                polylabel_features.append(f)

    fc = geojson.FeatureCollection(polylabel_features)
    click.echo(geojson.dumps(fc))
