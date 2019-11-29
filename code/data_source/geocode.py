"""
Geocode addresses using online service.

There are many available Geocoding services, but few that have acceptable terms
and conditions. Google requires results to not be cached and to be shown on a
Google map. Mapbox requires results to not be cached. I like geocode.earth
because they're maintainers of Pelias, but they have no persistent free tier:
it's only a two week trial.

For now, I'm going to use https://opencagedata.com/, which looks like it has a
perpetual free tier of 2500 queries a day, and also doesn't have restrictions.

The Census' geocoding may be worthwhile to check out, but I'd suspect it's not
as good as a private solution. https://geocoding.geo.census.gov/

Here's a sample result for the query '209 Oakland Ave, Pittsburgh PA 15213':

```py
[{
    'annotations': {
        'DMS': {
            'lat': "40° 26' 28.93092'' N",
            'lng': "79° 57' 23.66892'' W"
        },
        'FIPS': {
            'county': '42003',
            'state': '42'
        },
        'MGRS': '17TNE8849177269',
        'Maidenhead': 'FN00ak55fw',
        'Mercator': {
            'x': -8900725.181,
            'y': 4902567.019
        },
        'OSM': {
            'edit_url':
                'https://www.openstreetmap.org/edit?node=5240344579#map=16/40.44137/-79.95657',
            'url':
                'https://www.openstreetmap.org/?mlat=40.44137&mlon=-79.95657#map=16/40.44137/-79.95657'
        },
        'UN_M49': {
            'regions': {
                'AMERICAS': '019',
                'NORTHERN_AMERICA': '021',
                'US': '840',
                'WORLD': '001'
            },
            'statistical_groupings': ['MEDC']
        },
        'callingcode': 1,
        'currency': {
            'alternate_symbols': ['US$'],
            'decimal_mark': '.',
            'disambiguate_symbol': 'US$',
            'html_entity': '$',
            'iso_code': 'USD',
            'iso_numeric': '840',
            'name': 'United States Dollar',
            'smallest_denomination': 1,
            'subunit': 'Cent',
            'subunit_to_unit': 100,
            'symbol': '$',
            'symbol_first': 1,
            'thousands_separator': ','
        },
        'flag': '🇺🇸',
        'geohash': 'dppnhd1khc8xn1pwq6mf',
        'qibla': 54.42,
        'roadinfo': {
            'drive_on': 'right',
            'road': 'Oakland Avenue',
            'speed_in': 'mph'
        },
        'sun': {
            'rise': {
                'apparent': 1575030120,
                'astronomical': 1575024360,
                'civil': 1575028320,
                'nautical': 1575026340
            },
            'set': {
                'apparent': 1575064440,
                'astronomical': 1575070200,
                'civil': 1575066240,
                'nautical': 1575068220
            }
        },
        'timezone': {
            'name': 'America/New_York',
            'now_in_dst': 0,
            'offset_sec': -18000,
            'offset_string': '-0500',
            'short_name': 'EST'
        },
        'what3words': {
            'words': 'goods.gasp.tags'
        }
    },
    'bounds': {
        'northeast': {
            'lat': 40.4414197,
            'lng': -79.9565247
        },
        'southwest': {
            'lat': 40.4413197,
            'lng': -79.9566247
        }
    },
    'components': {
        'ISO_3166-1_alpha-2': 'US',
        'ISO_3166-1_alpha-3': 'USA',
        '_type': 'building',
        'city': 'Pittsburgh',
        'continent': 'North America',
        'country': 'USA',
        'country_code': 'us',
        'county': 'Allegheny County',
        'house': 'Amazon@Pitt',
        'house_number': '209',
        'neighbourhood': 'Oakland',
        'postcode': '15213',
        'road': 'Oakland Avenue',
        'state': 'Pennsylvania',
        'state_code': 'PA',
        'suburb': 'Central Oakland'
    },
    'confidence':
        10,
    'formatted':
        'Amazon@Pitt, 209 Oakland Avenue, Pittsburgh, PA 15213, United States of America',
    'geometry': {
        'lat': 40.4413697,
        'lng': -79.9565747
    }
}]
```
"""

import os

from dotenv import load_dotenv
from opencage.geocoder import OpenCageGeocode
from shapely.geometry import Point


class Geocode(object):
    """docstring for Geocode"""
    def __init__(self):
        super(Geocode, self).__init__()

        load_dotenv()
        self.api_key = os.getenv('OPENCAGEDATA_API_KEY')
        assert self.api_key is not None, 'Opencagedata api key missing'
        self.geocoder = OpenCageGeocode(self.api_key)

    def search(self, query: str, proximity: Point = None):
        """Forward geocode using opencagedata.com

        Args:
            - query: address as a string to query on
            - proximity: Point to give the geocoder a hint

        Returns:
            big dict of info. The most useful info is probably just
            [{'geometry': {
                'lat': 40.4413697,
                'lng': -79.9565747
            }}]
        """
        if proximity is not None:
            lon = proximity[0]
            lat = proximity[1]
            prox_str = f'{lat}, {lon}'
            result = self.geocoder.geocode(query, proximity=prox_str)
        else:
            result = self.geocoder.geocode(query)

        return result
