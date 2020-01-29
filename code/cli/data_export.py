"""
Note: Might be a good idea to merge all the land ownership files into a single vector tile dataset, with different layers
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
@click.option(
    '-b',
    '--buffer',
    required=True,
    type=float,
    help='Distance in miles for buffer around trail')
@click.option(
    '-a',
    '--attr',
    required=True,
    type=str,
    multiple=True,
    help=
    'Wikipedia page attributes to keep. Supply each value one at a time with multiple flags. Options are: categories, content, html, images, links, original_title, pageid, parent_id, references, revision_id, sections, summary, title, url'
)
def wikipedia_for_trail(trail_code, buffer, attr):
    """Get geotagged wikipedia articles near trail
    """
    # Instantiate trail class
    trail = Trail()

    # Get wikipedia articles
    gdf = trail.wikipedia_articles(
        buffer_dist=buffer, buffer_unit='mile', attrs=attr)

    # Write to stdout
    click.echo(gdf.to_json())


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
        'name', 'description', 'parkCode', 'fullName', 'images', 'wiki_url',
        'geometry'
    ]
    gdf = gdf[cols]

    # Print GeoJSON to stdout
    click.echo(gdf.to_json())
