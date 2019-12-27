"""
Script to run on AWS lambda to update wildfire perimeters

Layers used:

- geolambda: arn:aws:lambda:us-east-1:552188055668:layer:geolambda:4
- geolambda-python: arn:aws:lambda:us-east-1:552188055668:layer:geolambda-python:3
- nst-guide-geojson-python37: arn:aws:lambda:us-east-1:961053664803:layer:nst-guide-geojson-python37:1
- nst-guide-pyshp-python37: arn:aws:lambda:us-east-1:961053664803:layer:nst-guide-pyshp-python37:1
- Klayers-python37-requests: arn:aws:lambda:us-east-1:113088814899:layer:Klayers-python37-requests:9
"""

import json

import boto3

from nifc_current import NIFCCurrent

s3 = boto3.resource('s3')


def lambda_handler(event, context):
    """AWS Lambda entry point"""
    nifc = NIFCCurrent()
    gj = nifc.geojson()
    minified = json.dumps(json.loads(str(gj)), separators=(',', ':'))

    # Write individual GeoJSON file to S3
    obj = s3.Object('tiles.nst.guide', f'nifc/current.geojson')
    # 2-hour cache plus 24-hour stale-while-revalidate
    obj.put(
        Body=minified,
        ContentType='application/geo+json',
        CacheControl='public, max-age=7200, stale-while-revalidate=86400')
