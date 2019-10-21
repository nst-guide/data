# General downloads

import re
import urllib.request
from io import BytesIO
from pathlib import Path
from subprocess import run
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

import fiona
import geojson
import geopandas as gpd
import gpxpy
import gpxpy.gpx
import pandas as pd
import pint
import requests
from fiona.io import ZipMemoryFile
from geopandas.tools import sjoin
from lxml import etree as ET
from shapely.geometry import LineString, MultiLineString, box, mapping, shape
from shapely.ops import linemerge

import util


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
            osm_path = folder / f'{state}-latest.osm.pbf'
            url = 'http://download.geofabrik.de/north-america/us-west-latest.osm.pbf'
            urllib.request.urlretrieve(url, osm_path)

        # Get buffer from USFS track
        path = self.data_dir / 'pct' / 'polygon' / 'usfs' / 'buffer20mi.geojson'
        with path.open() as f:
            p = geojson.load(f)

        # Create OSM extract around trail
        buffer = shape(p['geometry'])
        poly_text = util.coords_to_osm_poly(list(buffer.exterior.coords))
        states = ['california', 'oregon', 'washington']

        with NamedTemporaryFile('w+', suffix='.poly') as tmp:
            tmp.write(poly_text)
            tmp.seek(0)

            # TODO: put intermediate extracts into a tmp directory
            for state in states:
                osm_path = folder / f'{state}-latest.osm.pbf'
                new_path = folder / f'{state}-pct.o5m'
                cmd = [
                    'osmconvert', osm_path, '--out-o5m', f'-B={tmp.name}', '>',
                    new_path
                ]
                cmd = ' '.join([str(x) for x in cmd])
                run(cmd, shell=True, check=True)

            cmd = 'osmconvert '
            for state in states:
                new_path = folder / f'{state}-pct.o5m'
                cmd += f'{new_path} '
            new_path = folder / f'pct.o5m'
            cmd += f'-o={new_path}'
            run(cmd, shell=True, check=True)

            # Now pct.o5m exists on disk and includes everything within a 20
            # mile buffer


    def get_pct_track(self):
        path = self.data_dir / 'raw' / 'osm' / 'pct.o5m'
        if not path.exists():
            self.download_extracts()

        new_path = self.data_dir / 'raw' / 'osm' / 'pct_dependents.osm'

        # Use osmfilter to get just the PCT relation and its dependents
        pct_relation_id = 1225378
        cmd = f'osmfilter {path} --keep-relations="@id={pct_relation_id}" '
        cmd += f'--keep-ways= --keep-nodes= -o={new_path}'
        run(cmd, shell=True, check=True)

        # Open XML
        f = open(new_path)
        parser = ET.parse(f)
        doc = parser.getroot()

        # Get PCT relation
        pct = doc.find(f"relation/[@id='{pct_relation_id}']")

        # Get list of ways
        # These are references to way ids
        way_refs = pct.findall("member/[@type='way']")
        ways = [doc.find(f"way/[@id='{member.get('ref')}']") for member in way_refs]

        nodes = []
        # NOTE None can be in ways. Maybe for ways outside the bbox of this osm file
        for way in ways:
            node_refs = way.findall('nd')
            nodes.extend([doc.find(f"node/[@id='{member.get('ref')}']") for member in node_refs])

        for n in nodes:
            if n is None:
                print('isnone')
                break

        points = [(float(n.get('lon')), float(n.get('lat'))) for n in nodes if n is not None]

        ls = geojson.LineString(points)
        save_dir = self.data_dir / 'pct' / 'line' / 'osm'
        save_dir.mkdir(parents=True, exist_ok=True)

        with open(save_dir / 'full.geojson', 'w') as f:
            geojson.dump(ls, f)



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

    def downloaded(self) -> bool:
        """Check if files are downloaded"""
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
            features.append(
                geojson.Feature(geometry=mapping(bbox),
                                properties={'name': name}))

        fc = geojson.FeatureCollection(features)

        save_dir = self.data_dir / 'pct' / 'polygon' / 'halfmile'
        save_dir.mkdir(parents=True, exist_ok=True)
        with open(save_dir / 'bbox.geojson', 'w') as f:
            geojson.dump(fc, f)

    def trail(self) -> gpd.GeoDataFrame:
        """Get Halfmile trail as GeoDataFrame
        """
        if self.downloaded():
            path = self.save_dir / 'full.geojson'
            trail = gpd.read_file(path)
            return trail

        raise ValueError('trails not yet downloaded')


class USFS(DataSource):
    """docstring for USFS"""
    def __init__(self):
        super(USFS, self).__init__()

    def downloaded(self) -> bool:
        save_dir = self.data_dir / 'pct' / 'line' / 'usfs'
        files = ['full.geojson']
        return all((save_dir / f).exists() for f in files)

    def download(self):
        url = 'https://www.fs.usda.gov/Internet/FSE_DOCUMENTS/stelprdb5332131.zip'
        r = requests.get(url)
        with ZipMemoryFile(BytesIO(r.content)) as z:
            with z.open('PacificCrestTrail.shp') as collection:
                fc = list(collection)

        multilinestrings = []
        for feature in fc:
            multilinestrings.append(shape(feature['geometry']))

        # There's at least one multilinestring in the shapefile. This needs to
        # be converted to linestring before I can use linemerge()
        linestrings = []
        for line in multilinestrings:
            if isinstance(line, LineString):
                linestrings.append(line)
            elif isinstance(line, MultiLineString):
                linestrings.extend(line)

        full = linemerge(linestrings)

        # Reproject from EPSG 3310 to WGS84 (EPSG 4326)
        full = util.reproject(full, 'epsg:3310', 'epsg:4326')
        feature = geojson.Feature(geometry=mapping(full))

        save_dir = self.data_dir / 'pct' / 'line' / 'usfs'
        save_dir.mkdir(parents=True, exist_ok=True)
        with open(save_dir / 'full.geojson', 'w') as f:
            geojson.dump(feature, f)

    def trail(self) -> gpd.GeoDataFrame:
        """Load trail into GeoDataFrame"""

        if self.downloaded():
            path = self.data_dir / 'pct' / 'line' / 'usfs' / 'full.geojson'
            trail = gpd.read_file(path)
            return trail

        raise ValueError('trails not yet downloaded')

    def buffer(self, distance=20):
        """Create buffer around USFS pct track

        Args:
            distance: buffer radius in miles
        """
        path = self.data_dir / 'pct' / 'line' / 'usfs' / 'full.geojson'
        if not path.exists():
            self.download()

        with open(path) as f:
            linestring = geojson.load(f)

        l = shape(linestring['geometry'])

        # Reproject to EPSG 3488
        l_new = util.reproject(l, 'epsg:4326', 'epsg:3488')

        # Make 20 mile buffer for now
        ureg = pint.UnitRegistry()
        miles = distance
        meters = (miles * ureg.miles).to(ureg.meters).magnitude
        polygon = l_new.buffer(meters)

        # Reproject back to EPSG 4326
        polygon_new = util.reproject(polygon, 'epsg:3488', 'epsg:4326')
        feature = geojson.Feature(geometry=mapping(polygon_new))

        save_dir = self.data_dir / 'pct' / 'polygon' / 'usfs'
        save_dir.mkdir(parents=True, exist_ok=True)
        with open(save_dir / f'buffer{distance}mi.geojson', 'w') as f:
            geojson.dump(feature, f)
        linestring['geometry'].keys()


class WildernessBoundaries(DataSource):
    def __init__(self):
        super(WildernessBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.save_dir.mkdir(exist_ok=True, parents=True)

    def downloaded(self) -> bool:
        files = ['full.geojson']
        return all((self.save_dir / f).exists() for f in files)

    def download(self):
        """Download shapefile of wilderness boundaries and intersect with PCT track
        """

        # Load the FeatureCollection into a GeoDataFrame
        url = 'http://www.wilderness.net/GIS/Wilderness_Areas.zip'
        r = requests.get(url)
        with fiona.BytesCollection(bytes(r.content)) as f:
            crs = f.crs
            gdf = gpd.GeoDataFrame.from_features(f, crs=crs)

        # Reproject to WGS84
        gdf = gdf.to_crs(epsg=4326)

        # Load Halfmile track for intersections
        trail = Halfmile().trail()
        trail = trail.to_crs(epsg=4326)

        # Intersect with the trail
        intersection = sjoin(gdf, trail, how='inner')

        # Save to GeoJSON
        intersection.to_file(self.save_dir / 'wilderness.geojson', driver='GeoJSON')
