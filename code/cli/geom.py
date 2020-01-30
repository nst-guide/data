from copy import deepcopy

import click
import geojson
from shapely.algorithms.polylabel import polylabel as polylabel_fn
from shapely.geometry import shape

from geom import validate_geojson


@click.command()
@click.option(
    '-x',
    '--exclude',
    type=str,
    multiple=True,
    default=None,
    required=False,
    help=
    "Exclude the named attributes from all features. You can specify multiple -x options to exclude several attributes. (Don't comma-separate names within a single -x.)"
)
@click.option(
    '-y',
    '--include',
    type=str,
    multiple=True,
    default=None,
    required=False,
    help=
    "Include the named attributes in all features, excluding all those not explicitly named. You can specify multiple -y options to explicitly include several attributes. (Don't comma-separate names within a single -y.)"
)
@click.option(
    '-X',
    '--exclude-all',
    is_flag=True,
    default=False,
    required=False,
    help="Exclude all attributes and encode only geometries")
@click.argument(
    'file',
    required=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True))
def polylabel(exclude, include, exclude_all, file):
    """Create point labels for polygon features

    Adds the 'rank' property, which is the percentage of the total area of a
    multipolygon that an inner polygon takes up.
    """
    # If more than one of exclude, include, and exclude_all are provided, raise
    # exception
    if sum(map(bool, [exclude, include, exclude_all])) > 1:
        msg = 'Only one of exclude, include, and exclude_all may be provided'
        raise ValueError(msg)

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

        # Handle properties
        if exclude:
            props = {k: v for k, v in props.items() if k not in exclude}
        if include:
            props = {k: v for k, v in props.items() if k in include}
        if exclude_all:
            props = {}

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
