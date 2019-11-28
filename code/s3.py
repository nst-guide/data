from subprocess import run
from tempfile import TemporaryDirectory

from pipeline import geojson_to_tiles


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
