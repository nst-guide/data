# General downloads

import re
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import geojson
import geopandas as gpd
import gpxpy
import gpxpy.gpx
import requests
from shapely.geometry import LineString, mapping
from shapely.ops import linemerge

# self = Download()


def in_ipython():
    try:
        return __IPYTHON__
    except NameError:
        return False


class Download:
    def __init__(self):
        self.data_dir = self.find_data_dir()

    def find_data_dir(self):
        if in_ipython():
            # Note, this will get the path of the file this is called from;
            # __file__ doesn't exist in IPython
            cwd = Path().absolute()
        else:
            cwd = Path(__file__).absolute()

        data_dir = (cwd / '..' / 'data' / 'pct').resolve()
        return data_dir

    def halfmile(self):
        urls = [
            'https://www.pctmap.net/wp-content/uploads/pct/ca_state_gps.zip',
            'https://www.pctmap.net/wp-content/uploads/pct/or_state_gps.zip',
            'https://www.pctmap.net/wp-content/uploads/pct/wa_state_gps.zip'
        ]
        headers = {
            'User-Agent':
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36',
        }

        # Collection of shapely LineStrings
        routes = {
            'full': [],
            'sections': [],
            'alt': [],
        }

        name_re = re.compile(r'^((?:CA|OR|WA) Sec [A-Z])(?: - (.+))?$')

        for url in urls:
            r = requests.get(url, headers=headers)
            z = ZipFile(BytesIO(r.content))
            names = z.namelist()
            names = [x for x in names if '__MACOSX' not in x]
            names = [x for x in names if 'tracks' in x]
            names = sorted(names)

            for name in names:
                gpx = gpxpy.parse(z.read(name).decode('utf-8'))

                for track in gpx.tracks:
                    assert len(track.segments) == 1
                    line = [(x.longitude, x.latitude, x.elevation)
                            for x in track.segments[0].points]
                    linestring = LineString(line)

                    section_name, alt_name = name_re.match(track.name).groups()

                    d = {'line': linestring}
                    if not alt_name:
                        d['name'] = section_name

                        routes['sections'].append(d)

                    else:
                        d['name'] = alt_name

                        routes['alt'].append(d)

        # Create full route from sections
        sects = [x['line'] for x in routes['sections']]
        full = linemerge(sects)
        routes['full'] = full

        # Serialize to GeoJSON
        feature = geojson.Feature(geometry=mapping(full))
        save_dir = self.data_dir / 'line' / 'halfmile'
        save_dir.mkdir(parents=True, exist_ok=True)

        with open(save_dir / 'full.geojson', 'w') as f:
            geojson.dump(feature, f)

        # Create features from alternates
        features = [
            geojson.Feature(geometry=mapping(d['line']),
                            properties={'name': d['name']})
            for d in routes['alt']
        ]
        fc = geojson.FeatureCollection(features)

        with open(save_dir / 'alternates.geojson', 'w') as f:
            geojson.dump(fc, f)

    def usfs_track():
        url = 'https://www.fs.usda.gov/Internet/FSE_DOCUMENTS/stelprdb5332131.zip'
        r = requests.get(url)
        z = ZipFile(BytesIO(r.content))
        with TemporaryDirectory() as d:
            z.extractall(d)
            shp = gpd.read_file(d + '/PacificCrestTrail.shp')

        z.namelist()
