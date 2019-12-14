import logging
import re
import sys

import click

from package_tiles import package_tiles as _package_tiles

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
Log = logging.getLogger()


@click.group()
def main():
    pass


@main.command()
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


if __name__ == '__main__':
    main()
