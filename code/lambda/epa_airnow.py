"""
Script to run on AWS lambda to update air quality polygons

Layers used:

- geolambda: arn:aws:lambda:us-east-1:552188055668:layer:geolambda:4
- geolambda-python: arn:aws:lambda:us-east-1:552188055668:layer:geolambda-python:3
- Klayers-python37-requests: arn:aws:lambda:us-east-1:113088814899:layer:Klayers-python37-requests:9
- nst-guide-fastkml-python37: arn:aws:lambda:us-east-1:961053664803:layer:nst-guide-fastkml-python37:2
- nst-guide-geojson-python37: arn:aws:lambda:us-east-1:961053664803:layer:nst-guide-geojson-python37:1
"""

import json

import boto3

from epa import EPAAirNow

s3 = boto3.resource('s3')


def lambda_handler(event, context):
    """AWS Lambda entry point"""
    airnow = EPAAirNow()
    # Eventually also set to Ozone, Combined
    air_measure = 'PM25'
    gj = airnow.current_air_quality(air_measure=air_measure)

    # If HTTP response is not 200, None is returned
    if gj is None:
        return

    minified = json.dumps(json.loads(str(gj)), separators=(',', ':'))

    # Write individual GeoJSON file to S3
    obj = s3.Object('tiles.nst.guide', f'airnow/{air_measure}.geojson')
    # 2-hour cache plus 24-hour stale-while-revalidate
    obj.put(
        Body=minified,
        ContentType='application/geo+json',
        CacheControl='public, max-age=7200, stale-while-revalidate=86400')
