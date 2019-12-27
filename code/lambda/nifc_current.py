"""
Script to run on AWS lambda to update wildfire perimeters
"""

import json

import boto3

from nifc_current import NIFCCurrent

s3 = boto3.resource('s3')


def lambda_handler(event, context):
    nifc = NIFCCurrent()
    gj = nifc.geojson()
    minified = json.dumps(json.loads(str(gj)), separators=(',', ':'))

    # Write individual GeoJSON file to S3
    obj = s3.Object('tiles.nst.guide', f'nifc/current.geojson')
    obj.put(Body=minified, ContentType='application/geo+json')
