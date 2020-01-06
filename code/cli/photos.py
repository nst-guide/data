import json
import logging
import sys
from pathlib import Path
from shutil import copyfile
from subprocess import run

import click

from data_source import GPSTracks, PhotosLibrary

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
Log = logging.getLogger()


# album = None
# exif = True
# all_cols = True
# out_path = 'photos.json'
# start_date = '2019-04-22'
# end_date = '2019-10-01'
# xw_path = None
# geotag_photos(album, start_date, end_date, exif, all_cols, out_path, xw_path)
@click.command()
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


@click.command()
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

    For any non-JPEG files, this calls `sips` (mac-cli) to convert them to JPEG.
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
        # If the existing file extension is already jpeg, just copy the file and
        # don't run `sips`
        new_file = out_dir / (new_stub + '.jpeg')
        if Path(existing_file).suffix == '.jpeg':
            copyfile(existing_file, new_file)
        # If the file extension is not jpeg, convert it to jpeg using `sips`
        else:
            cmd = [
                'sips',
                str(existing_file), '-s', 'format', 'jpeg', '--out',
                str(new_file)
            ]
            run(cmd, check=True)


# @main.command()
# @click.option(
#     '-p',
#     '--photos_xw',
#     required=True,
#     type=click.Path(
#         exists=True, file_okay=True, dir_okay=False, resolve_path=True),
#     help='Path to photos.geojson')
# @click.argument(
#     'file',
#     type=click.Path(
#         exists=True, file_okay=True, dir_okay=False, resolve_path=True),
#     nargs=1)
# def show_photo(photos_xw, file):
#     """Copy files to out_dir using JSON crosswalk
#
#     file should be path to photo
#     """
#     # Load JSON crosswalk
#     with open(photos_xw) as f:
#         xw = json.load(f)
#
#     # Find named file
#     file = '/Users/kyle/Pictures/Photos Library.photoslibrary/private/com.apple.Photos/ExternalEditSessions/6E3866C6-C618-4AE6-907F-D324F861DA3F/IMG_2188.png'
#     [x for x in xw['features'] if x['properties']['path'] == file]
#     xw['features'][0]
#
#     photos_xw = '../photos.json'
#
#     # Keys should be existing paths to photos; values are UUIDs, i.e. stubs
#     # without extensions for file names
#
#     # First, make sure all keys exist
#     for key in xw.keys():
#         assert Path(key).exists(), f'Key does not exist:\n{key}'
#
#     # Make out_dir
#     out_dir = Path(out_dir)
#     out_dir.mkdir(exist_ok=True, parents=True)
#
#     # Iterate over values; copying files
#     for existing_file, new_stub in xw.items():
#         new_file = out_dir / (new_stub + Path(existing_file).suffix)
#         copyfile(existing_file, new_file)
#
#
