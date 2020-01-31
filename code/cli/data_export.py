import click

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
def wikipedia(trail_code, buffer, attr):
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


@click.command()
@click.option(
    '-t',
    '--trail-code',
    required=True,
    type=str,
    help='Code for desired trail, .e.g "pct"')
def national_forests(trail_code):
    """Get national forests info for trail
    """
    if trail_code != 'pct':
        raise ValueError('invalid trail_code')

    # Instantiate trail class
    trail = Trail()

    # Generate information for national parks the trail passes through
    gdf = trail.national_forests()

    # Make column names lower case
    gdf.columns = gdf.columns.str.lower()

    # Keep desired columns
    cols = [
        'forestname', 'gis_acres', 'geometry', 'length', 'wiki_image',
        'wiki_url', 'wiki_summary', 'official_url'
    ]
    gdf = gdf[cols]

    # Print GeoJSON to stdout
    click.echo(gdf.to_json())


@click.command()
@click.option(
    '-t',
    '--trail-code',
    required=True,
    type=str,
    help='Code for desired trail, .e.g "pct"')
def wilderness(trail_code):
    """Get wilderness info for trail
    """
    if trail_code != 'pct':
        raise ValueError('invalid trail_code')

    # Instantiate trail class
    trail = Trail()

    # Generate information for national parks the trail passes through
    gdf = trail.wildernesses()

    # Make column names lower case
    gdf.columns = gdf.columns.str.lower()

    # Keep desired columns
    gdf = gdf.set_index('wid')
    cols = [
        'url', 'name', 'acreage', 'descriptio', 'agency', 'yeardesign',
        'geometry', 'length', 'wiki_image', 'wiki_url', 'wiki_summary'
    ]
    gdf = gdf[cols]

    # Print GeoJSON to stdout
    click.echo(gdf.to_json())


@click.command()
@click.option(
    '-t',
    '--trail-code',
    required=True,
    type=str,
    help='Code for desired trail, .e.g "pct"')
def wildfire_historical(trail_code):
    """Get historical wildfire info for trail
    """
    if trail_code != 'pct':
        raise ValueError('invalid trail_code')

    # Instantiate trail class
    trail = Trail()

    # Generate information for national parks the trail passes through
    gdf = trail.wildfire_historical()

    # Make column names lower case
    gdf.columns = gdf.columns.str.lower()

    # Keep desired columns
    cols = [
        'year', 'name', 'acres', 'inciwebid', 'geometry', 'length',
        'wiki_image', 'wiki_url', 'wiki_summary'
    ]
    gdf = gdf[cols]

    # Print GeoJSON to stdout
    click.echo(gdf.to_json())


@click.command()
@click.option(
    '-t',
    '--trail-code',
    required=True,
    type=str,
    help='Code for desired trail, .e.g "pct"')
def town_boundaries(trail_code):
    """Get town boundaries for trail
    """
    if trail_code != 'pct':
        raise ValueError('invalid trail_code')

    # Instantiate trail class
    trail = Trail()

    # Generate information for national parks the trail passes through
    gdf = trail.towns()

    # Make column names lower case
    gdf.columns = gdf.columns.str.lower()

    # Make section lower case
    gdf['section'] = gdf['section'].str.lower()

    # Set town id's as index
    gdf = gdf.set_index('id')

    # Print GeoJSON to stdout
    click.echo(gdf.to_json())
