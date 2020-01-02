import json
import logging
import re
import sys
from pathlib import Path
from shutil import copyfile

import click

from data_source import GPSTracks, PhotosLibrary
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


@main.command()
@click.option(
    '-a',
    '--album',
    required=False,
    type=str,
    multiple=True,
    default=None,
    help='Photos.app album to use for photos geocoding.')
@click.option(
    '--exif',
    is_flag=True,
    default=False,
    help='Include metadata from exiftool')
@click.option(
    '--all-cols',
    is_flag=True,
    default=False,
    help="Don't select minimal columns")
@click.option(
    '-o',
    '--out-path',
    required=True,
    type=click.Path(
        exists=False, file_okay=True, dir_okay=False, resolve_path=True),
    help='Output path for UUID-photo path crosswalk')
@click.option(
    '-s',
    '--start-date',
    required=False,
    type=str,
    default=None,
    help='Start date to find photos')
@click.option(
    '-e',
    '--end-date',
    required=False,
    type=str,
    default=None,
    help='End date to find photos')
@click.option(
    '-x',
    '--xw-path',
    required=False,
    default=None,
    type=click.Path(
        exists=False, file_okay=True, dir_okay=False, resolve_path=True),
    help='Output path for UUID-photo path crosswalk')
def geotag_photos(
        album, start_date, end_date, exif, all_cols, out_path, xw_path):
    """Geotag photos from album using watch's GPS tracks
    """
    # Instantiate Photos and GPSTracks classes
    photos_library = PhotosLibrary()
    tracks = GPSTracks()

    # Get GeoDataFrame of GPS points
    points = tracks.points_df()

    # Get photos in given album
    photos = photos_library.find_photos(
        albums=album, exif=exif, start_date=start_date, end_date=end_date)

    # Geotag those photos
    gdf = photos_library.geotag_photos(photos, points)

    # If path_edited exists, replace path with the edited path
    gdf.loc[gdf['path_edited'].notna(
    ), 'path'] = gdf.loc[gdf['path_edited'].notna(), 'path_edited']

    # Check for duplicates
    # If there are duplicates on date (at the second level), try to keep the one
    # with original_filename ending in JPG
    # Singe my photos end in either .ARW, .JPG, or .HEIC, I'll just sort on date
    # and then original_filename, and the one ending in JPG will be last.
    #
    # Sort based on date and original_filename
    gdf = gdf.sort_values(['date', 'original_filename'])
    # Group by date, and then keep the last one
    gdf = gdf.groupby('date').tail(1)

    # Generate features and uuid-path crosswalk
    gdf['date'] = gdf['date'].apply(lambda x: x.isoformat())
    cols = ['uuid', 'favorite', 'keywords', 'description', 'date', 'geometry']
    if all_cols:
        # Manually add a few more columns
        other_cols = [
            'path', 'GPSAltitude', 'GPSDateTime', 'GPSLatitude', 'GPSLongitude',
            'GPSSpeedRef', 'GPSSpeed', 'GPSImgDirectionRef', 'GPSImgDirection',
            'GPSHPositioningError'
        ]
        cols.extend(other_cols)

    fc = gdf[cols].set_index('uuid').to_json()

    Path(out_path).resolve().parents[0].mkdir(exist_ok=True, parents=True)
    with open(out_path, 'w') as f:
        json.dump(json.loads(fc), f, separators=(',', ':'))

    # Generate UUID-file path xw and write to disk
    if xw_path is not None:
        uuid_xw = gdf[['path', 'uuid']].set_index('path')['uuid'].to_dict()

        Path(xw_path).resolve().parents[0].mkdir(exist_ok=True, parents=True)
        with open(xw_path, 'w') as f:
            json.dump(uuid_xw, f)


@main.command()
@click.option(
    '-o',
    '--out-dir',
    required=True,
    type=click.Path(
        exists=False, file_okay=True, dir_okay=False, resolve_path=True),
    help='Output path for UUID-photo path crosswalk')
@click.argument(
    'file',
    type=click.Path(
        exists=True, file_okay=True, dir_okay=False, resolve_path=True),
    nargs=1)
def copy_using_xw(file, out_dir):
    """Copy files to out_dir using JSON crosswalk
    """
    # Load JSON crosswalk
    with open(file) as f:
        xw = json.load(f)

    # Keys should be existing paths to photos; values are UUIDs, i.e. stubs
    # without extensions for file names

    # First, make sure all keys exist
    for key in xw.keys():
        assert Path(key).exists(), f'Key does not exist:\n{key}'

    # Make out_dir
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True, parents=True)

    # Iterate over values; copying files
    for existing_file, new_stub in xw.items():
        new_file = out_dir / (new_stub + Path(existing_file).suffix)
        copyfile(existing_file, new_file)


if __name__ == '__main__':
    main()
