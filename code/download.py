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
import pandas as pd
import requests
from shapely.geometry import LineString, mapping, box, shape
from shapely.ops import linemerge

import urllib.request
import util
from subprocess import run

def in_ipython():
    try:
        return __IPYTHON__
    except NameError:
        return False


def find_data_dir():
    if in_ipython():
        # Note, this will get the path of the file this is called from;
        # __file__ doesn't exist in IPython
        cwd = Path().absolute()
    else:
        cwd = Path(__file__).absolute()

    data_dir = (cwd / '..' / 'data').resolve()
    return data_dir


class DataSource:
    def __init__(self):
        self.data_dir = find_data_dir()


class OpenStreetMap(DataSource):
    """docstring for OpenStreetMap"""
    def __init__(self):
        super(OpenStreetMap, self).__init__()
        self.trail_ids = {'pct': 1225378}

    def download_extracts(self):
        """Downloads extracts from geofabrik, then creates an .o5m file using bounding boxes created from each section of Halfmile data
        """

        # Download US West extract from geofabrik
        folder = self.data_dir / 'raw' / 'osm'
        folder.mkdir(parents=True, exist_ok=True)

        for state in ['california', 'oregon', 'washington']:
            path = folder / f'{state}-latest.osm.pbf'
            url = 'http://download.geofabrik.de/north-america/us-west-latest.osm.pbf'
            urllib.request.urlretrieve(url, path)

        # Get bounding boxes for each section of the trail from halfmile
        with open(self.data_dir / 'pct' / 'polygon' / 'halfmile' / 'bbox.geojson') as f:
            bboxes = geojson.load(f)

        for bbox_feature in bboxes['features']:
            polygon = shape(bbox_feature['geometry'])
            bbox_str = ','.join(str(x) for x in polygon.bounds)
            name = bbox_feature['properties']['name']
            name = name.lower().replace(' ', '_')

            new_path = folder / f'{name}.o5m'

            if name == 'ca_sec_r':
                path = [folder / f'{state}-latest.osm.pbf' for state in ['california', 'oregon']]
                path = ' '.join([(str(x)) for x in path])
            elif name == 'wa_sec_h':
                path = [folder / f'{state}-latest.osm.pbf' for state in ['oregon', 'washington']]
                path = ' '.join([(str(x)) for x in path])
            elif name.startswith('ca'):
                path = folder / 'california-latest.osm.pbf'
            elif name.startswith('or'):
                path = folder / 'oregon-latest.osm.pbf'
            elif name.startswith('wa'):
                path = folder / 'washington-latest.osm.pbf'

            cmd = [
                'osmconvert',
                path,
                '--out-o5m',
                f'-b={bbox_str}',
                '>',
                new_path
            ]
            cmd = ' '.join([str(x) for x in cmd])
            run(cmd, shell=True, check=True)



class StatePlaneZones(DataSource):
    """docstring for StatePlaneZones"""
    def __init__(self):
        super(StatePlaneZones, self).__init__()

    def downloaded(self):
        return (self.data_dir / 'proj' / 'state_planes.geojson').exists()

    def download(self):
        # Helpful list of state planes and their boundaries
        url = 'http://sandbox.idre.ucla.edu/mapshare/data/usa/other/spcszn83.zip'
        zones = gpd.read_file(url)
        epsg_zones = pd.read_csv(self.data_dir / 'proj' / 'state_planes.csv')
        zones = zones.merge(epsg_zones,
                            left_on='ZONENAME',
                            right_on='zone',
                            validate='1:1')

        minimal = zones[['geometry', 'epsg', 'zone']]
        minimal = minimal.rename(columns={'zone': 'name'})
        minimal.to_file(self.data_dir / 'proj' / 'state_planes.geojson',
                        driver='GeoJSON')


class Halfmile(DataSource):
    """docstring for Halfmile"""
    def __init__(self):
        super(Halfmile, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'line' / 'halfmile'
        self.save_dir.mkdir(parents=True, exist_ok=True)


    def downloaded(self):
        files = ['full.geojson', 'alternates.geojson', 'sections.geojson']
        return all((self.save_dir / f).exists() for f in files)


    def download(self):
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


        # Save sections as individual geojson
        features = [
            geojson.Feature(geometry=mapping(d['line']),
                            properties={'name': d['name']})
            for d in routes['sections']
        ]
        fc = geojson.FeatureCollection(features)
        with open(self.save_dir / 'sections.geojson', 'w') as f:
            geojson.dump(fc, f)

        # Create bounding boxes for each section
        self.create_bbox_for_sections()

        # Create full route from sections
        sects = [x['line'] for x in routes['sections']]
        full = linemerge(sects)
        routes['full'] = full

        # Serialize to GeoJSON
        feature = geojson.Feature(geometry=mapping(full))
        with open(self.save_dir / 'full.geojson', 'w') as f:
            geojson.dump(feature, f)

        # Create features from alternates
        features = [
            geojson.Feature(geometry=mapping(d['line']),
                            properties={'name': d['name']})
            for d in routes['alt']
        ]
        fc = geojson.FeatureCollection(features)

        with open(self.save_dir / 'alternates.geojson', 'w') as f:
            geojson.dump(fc, f)


    def create_bbox_for_sections(self):
        with open(self.save_dir / 'sections.geojson') as f:
            fc = geojson.load(f)

        features = []
        for feature in fc['features']:
            name = feature['properties']['name']
            bounds = LineString(feature['geometry']['coordinates']).bounds
            bbox = box(*bounds)
            features.append(geojson.Feature(geometry=mapping(bbox), properties={'name': name}))

        fc = geojson.FeatureCollection(features)

        save_dir = self.data_dir / 'pct' / 'polygon' / 'halfmile'
        save_dir.mkdir(parents=True, exist_ok=True)
        with open(save_dir / 'bbox.geojson', 'w') as f:
            geojson.dump(fc, f)


class USFS(DataSource):
    """docstring for USFS"""
    def __init__(self):
        super(USFS, self).__init__()

    def download():
        url = 'https://www.fs.usda.gov/Internet/FSE_DOCUMENTS/stelprdb5332131.zip'
        r = requests.get(url)
        z = ZipFile(BytesIO(r.content))
        # Use zipMemoryFile to have no I/O
        # https://fiona.readthedocs.io/en/latest/manual.html#memoryfile-and-zipmemoryfile
        with TemporaryDirectory() as d:
            z.extractall(d)
            shp = gpd.read_file(d + '/PacificCrestTrail.shp')

        z.namelist()
