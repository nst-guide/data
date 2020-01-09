import logging
import re
import sys

import click
import geopandas as gpd
import pandas as pd

import geom
from package_tiles import package_tiles as _package_tiles
from tiles import tiles_for_polygon
from trail import Trail

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
Log = logging.getLogger()


@click.command()
@click.option(
    '-t',
    '--trail_code',
    required=True,
    type=str,
    help='Trail code, e.g. `pct`')
@click.option(
    '-s',
    '--trail_section',
    required=False,
    default=None,
    show_default=True,
    type=str,
    help='Trail section, e.g. `ca_south`')
@click.option(
    '-z', '--min-zoom', required=True, type=int, help='Min zoom level')
@click.option(
    '-Z', '--max-zoom', required=True, type=int, help='Max zoom level')
@click.option(
    '-b',
    '--trail_buffer',
    required=False,
    default=0,
    show_default=True,
    type=float,
    help='Distance in miles for trail buffer')
@click.option(
    '--town_buffer',
    required=False,
    default=0,
    show_default=True,
    type=float,
    help='Distance in miles for town buffer')
@click.option(
    '--alternates/--no-alternates',
    default=True,
    show_default=True,
    help='Include trail alternates')
@click.option(
    '--tms/--no-tms',
    default=False,
    show_default=True,
    help='Invert y coordinate (for tms)')
def tiles_for_trail(
        trail_code, trail_section, alternates, trail_buffer, town_buffer,
        min_zoom, max_zoom, tms):
    """Get map tile coordinates for trail
    """
    # Load geometries
    trail = Trail(trail_code=trail_code)
    track = trail.track(trail_section=trail_section, alternates=alternates)
    towns = trail.towns(trail_section=trail_section)

    # Create buffers
    if trail_buffer > 0:
        track.geometry = geom.buffer(track, distance=trail_buffer, unit='mile')

    if town_buffer > 0:
        towns.geometry = geom.buffer(towns, distance=town_buffer, unit='mile')

    # Combine into single polygon
    gdf = gpd.GeoDataFrame(pd.concat([track, towns], sort=False, axis=0))
    polygon = gdf.unary_union

    # Find tiles
    scheme = 'tms' if tms else 'xyz'
    zoom_levels = range(min_zoom, max_zoom + 1)
    tiles = tiles_for_polygon(polygon, zoom_levels=zoom_levels, scheme=scheme)

    # Coerce to strings like
    # [x, y, z]
    s = '\n'.join([f'[{t[0]}, {t[1]}, {t[2]}]' for t in tiles])
    click.echo(s)


@click.command()
@click.option(
    '-g',
    '--geometry',
    required=True,
    type=click.Path(
        exists=True, file_okay=True, dir_okay=False, resolve_path=True),
    help=
    'Geometries to use for packaging tiles. Can be any format readable by GeoPandas.'
)
@click.option(
    '-b',
    '--buffer',
    required=True,
    type=str,
    help=
    'Buffer distance (in miles) to use around provided geometries. If you want multiple buffer distances, pass as --buffer "2 5 10"'
)
@click.option(
    '-d',
    '--directory',
    type=click.Path(
        exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    required=True,
    multiple=True,
    help=
    'Directory root of tiles to package. If multiple options are provided, will package each of them.'
)
@click.option(
    '-t',
    '--tile-json',
    type=click.Path(
        exists=True, file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    default=(None, ),
    multiple=True,
    help=
    'Paths to tile.json files for each directory. If not provided, assumes a tile JSON file is at directory/tile.json. Otherwise, the same number of options as directory must be provided.'
)
@click.option(
    '-z',
    '--min-zoom',
    type=int,
    required=False,
    default=(None, ),
    multiple=True,
    help='Min zoom for each tile source')
@click.option(
    '-Z',
    '--max-zoom',
    type=int,
    required=False,
    default=(None, ),
    multiple=True,
    help='Max zoom for each tile source')
@click.option(
    '-o',
    '--output',
    type=click.Path(exists=False, writable=True, resolve_path=True),
    required=True,
    help='Output directory')
@click.option(
    '--raise/--no-raise',
    'raise_errors',
    default=True,
    help=
    'Whether to raise an error if a desired tile is not found in the directory.'
)
@click.option(
    '-v', '--verbose', is_flag=True, default=False, help='Verbose output')
def package_tiles(
        geometry, buffer, directory, tile_json, min_zoom, max_zoom, output,
        raise_errors, verbose):
    """Package tiles into directory based on distance from trail

    Example:
    python main.py package-tiles -g ../data/pct/polygon/bound/town/ca/acton.geojson -b "0 1 2" -d ~/Desktop -o out/
    """
    # Make sure that tile_json and directory have same dimensions
    if tile_json != (None, ):
        msg = 'tile-json and directory must be provided the same number of times'
        assert len(tile_json) == len(directory), msg

    # Make sure that min_zoom and directory have same dimensions
    if min_zoom != (None, ):
        msg = 'min-zoom and directory must be provided the same number of times'
        assert len(min_zoom) == len(directory), msg

    # Make sure that min_zoom and directory have same dimensions
    if max_zoom != (None, ):
        msg = 'max-zoom and directory must be provided the same number of times'
        assert len(max_zoom) == len(directory), msg

    # Convert buffer from str to tuple of float
    # I.e. -b "0 1 2" is passed into this function as "0 1 2", to be converted
    # to [0, 1, 2]
    buffer_dists = list(map(float, re.split(r'[ ,]', buffer)))

    # If any of tile_json, min_zoom, and max_zoom are not provided, then
    # generate a tuple of None with same length as source directories tuple
    if tile_json == (None, ):
        tile_json = [None] * len(directory)
    if min_zoom == (None, ):
        min_zoom = [0] * len(directory)
    if max_zoom == (None, ):
        max_zoom = [14] * len(directory)

    if verbose:
        Log.info('Running with params: ')
        Log.info(f'geometry_path={geometry}')
        Log.info(f'buffer_dists={buffer_dists}')
        Log.info(f'src_dirs={directory}')
        Log.info(f'tile_jsons={tile_json}')
        Log.info(f'min_zooms={min_zoom}')
        Log.info(f'max_zooms={max_zoom}')
        Log.info(f'out_dir={output}')
        Log.info(f'raise_errors={raise_errors}')

    _package_tiles(
        geometry_path=geometry,
        buffer_dists=buffer_dists,
        src_dirs=directory,
        tile_jsons=tile_json,
        min_zooms=min_zoom,
        max_zooms=max_zoom,
        out_dir=output,
        raise_errors=raise_errors,
        verbose=verbose)
