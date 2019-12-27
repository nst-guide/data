"""
Script to run on AWS lambda to update air quality polygons
"""

import json

import boto3

from epa import EPAAirNow

s3 = boto3.resource('s3')


def lambda_handler(event, context):
    airnow = EPAAirNow()
    # Eventually also set to Ozone, Combined
    air_measure = 'PM25'
    gj = airnow.current_air_quality(air_measure=air_measure)
    minified = json.dumps(json.loads(str(gj)), separators=(',', ':'))

    # Write individual GeoJSON file to S3
    obj = s3.Object('tiles.nst.guide', f'airnow/{air_measure}.geojson')
    obj.put(Body=minified, ContentType='application/geo+json')
