"""
Might be a good idea to merge all the land ownership files into a single vector tile dataset, with different layers
"""
import click
import pandas as pd

import data_source
from trail import Trail


@click.command()
@click.option(
    '-t',
    '--trail-code',
    required=True,
    type=str,
    help='Code for desired trail, .e.g "pct"')
def national_parks(trail_code):
    """Get national parks info for trail
    """
    if trail_code != 'pct':
        raise ValueError('invalid trail_code')

    # Instantiate trail class
    trail = Trail()

    # Generate information for national parks the trail passes through
    gdf = trail.national_parks()

    # Keep desired columns
    cols = [
        'length', 'directionsInfo', 'directionsUrl', 'url', 'weatherInfo',
        'name', 'description', 'parkCode', 'fullName'
    ]
    df = gdf[cols]

    # Load boundaries to attach this metadata to the polygons themselves
    nps_bounds = data_source.NationalParkBoundaries().polygon()

    # The metadata uses a newer version of unit codes
    nps_url_xw = {
        'sequ': 'seki',
        'kica': 'seki',
        'lach': 'noca',
    }
    # If the row is one of the above codes, apply the mapping
    nps_bounds['UNIT_CODE'] = nps_bounds['UNIT_CODE'].str.lower().apply(
        lambda x: nps_url_xw.get(x, x))

    # Keep desired columns
    cols = [
        'UNIT_CODE', 'geometry'
    ]
    nps_bounds = nps_bounds[cols]

    # Merge the two datasets
    gdf = pd.merge(nps_bounds, df, left_on='UNIT_CODE', right_on='parkCode')

    # Drop the extra unit code column from the merge
    gdf = gdf.drop('UNIT_CODE', axis=1)

    # Print GeoJSON to stdout
    click.echo(gdf.to_json())
