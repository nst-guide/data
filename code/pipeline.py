"""
Code that's meant to be run as part of a pipeline. For example, current wildfires and air quality is meant to be run often, so that the newest version is always on the server.

Data sources:

- Current wildfires
- Current weather forecasts
- Current air quality data
- Current Sentinel imagery
"""
import json
from pathlib import Path
from subprocess import run
from tempfile import TemporaryDirectory

from data import EPAAirNow, GeoMAC


def current_wildfire():
    geomac = GeoMAC()
    perimeters = geomac.get_active_perimeters()
    upload_geojson_to_s3(
        perimeters,
        bucket_path='current_wildfire',
        bucket_name='tiles.nst.guide')


def current_weather():
    """Cache weather.gov API responses
    """
    pass


def current_air_quality():
    """
    TODO: currently, there's a property named 'color' that has the air quality
    severity. An air quality color crosswalk is here:
    https://www3.epa.gov/airnow/tvweather/airnow_mapping.pdf

    It looks like the color is "abgr"??? aka reverse of rgba??

    Or will `style_id = 1` always be Moderate and `style_id = 2` always be
    Unhealthy for Sensitive Groups? Probably not.
    """
    airnow = EPAAirNow()
    for air_measure in ['PM25', 'Combined', 'Ozone']:
        geojson_data = airnow.download(air_measure=air_measure)
        upload_geojson_to_s3(
            geojson_data,
            bucket_path=f'current_air_quality_{air_measure}',
            bucket_name='tiles.nst.guide')


def current_sentinel_imagery():
    pass


def upload_geojson_to_s3(
        geojson_data: str, bucket_path: str,
        bucket_name: str = 'tiles.nst.guide'):
    """
    This takes a geojson, cuts it into tiles, then uploads to s3

    Args:
        - geojson_data: geojson as string
        - bucket_path: folder structure after bucket_name
        - bucket_name: name of s3 bucket
    """
    with TemporaryDirectory() as tmp:
        tiles_path = geojson_to_tiles(geojson_data, tmp)
        upload_directory_to_s3(
            local_path=tiles_path,
            bucket_name=bucket_name,
            bucket_path=bucket_path,
            content_type='x-protobuf',
            content_encoding='gzip')


def geojson_to_tiles(geojson_data: str, folder: str):
    """
    Args:
        - geojson_data: geojson as string
        - folder: path to directory (usually temporary) to write geojson and
            tiles to

    Returns:
        - path to top of folder structure where tiles are kept
    """

    # write GeoJSON to directory
    folder = Path(folder)
    geojson_path = folder / 'data.geojson'
    tiles_path = folder / 'tiles'
    with open(geojson_path, 'w') as f:
        json.dump(geojson_data, f)

    # run tippecanoe
    cmd = [
        'tippecanoe',
        '-zg',
        '--force',
        '-e',
        str(tiles_path),
        str(geojson_path),
    ]
    run(cmd, capture_output=True, check=True, encoding='utf-8')
    return tiles_path


def upload_directory_to_s3(
        local_path,
        bucket_path,
        bucket_name='tiles.nst.guide',
        content_type='x-protobuf',
        content_encoding='gzip'):
    """This uses AWS CLI and must be preconfigured

    Args:
        - local_path: path to directory on local computer
        - bucket_path: folder structure after bucket_name
        - bucket_name: name of s3 bucket
        - content_type: content type for uploaded data
        - content_encoding: content encoding for uploaded data
    """
    bucket_path = bucket_path.strip('/')
    bucket_name = bucket_name.strip('/')
    s3_url = f's3://{bucket_name}/{bucket_path}/'

    cmd = [
        'aws',
        's3',
        'cp',
        str(local_path),
        s3_url,
        '--recursive',
        '--content-type',
        content_type,
        '--content-encoding',
        content_encoding,
    ]
    run(cmd, capture_output=True, check=True, encoding='utf-8')
