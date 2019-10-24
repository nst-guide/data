# General downloads

import os
import re
from io import BytesIO
from pathlib import Path
from subprocess import run
from tempfile import NamedTemporaryFile
from urllib.request import urlretrieve
from zipfile import ZipFile

import fiona
import geojson
import geopandas as gpd
import gpxpy
import gpxpy.gpx
import pandas as pd
import pint
import requests
from dotenv import load_dotenv
from fiona.io import ZipMemoryFile
from geopandas.tools import sjoin
from lxml import etree as ET
from shapely.geometry import LineString, MultiLineString, box, mapping, shape
from shapely.ops import linemerge

import geom
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


class Towns(DataSource):
    """Town information

    For now, town boundaries are drawn by hand.
    """
    def __init__(self):
        super(Towns, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound' / 'town'

    def boundaries(self) -> gpd.GeoDataFrame:
        """Get town boundaries
        """
        files = list(self.save_dir.glob('*/*.geojson'))
        return pd.concat([gpd.read_file(f) for f in files])


class OpenStreetMap(DataSource):
    """docstring for OpenStreetMap"""
    def __init__(self):
        super(OpenStreetMap, self).__init__()
        self.trail_ids = {'pct': 1225378}
        self.raw_dir = self.data_dir / 'raw' / 'osm'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _download_states(self, states, overwrite=False):
        """Download state-level OSM extracts from geofabrik
        """
        for state in states:
            osm_path = self.raw_dir / f'{state}-latest.osm.pbf'
            url = f'http://download.geofabrik.de/north-america/us/{state}-latest.osm.pbf'
            if overwrite or (not osm_path.exists()):
                urlretrieve(url, osm_path)

    def create_extracts(self):
        """Creates .o5m file for buffer area around trail

        TODO: include town geometries
        """
        states = ['california', 'oregon', 'washington']
        self._download_states(states, overwrite=False)

        # Get town boundaries and buffer from USFS track
        # Then generate the union of the two
        # The length of the multipolygon created from `.unary_union` is 3, which
        # I believe means that all towns that currently have a hand-drawn
        # geometry (except Winthrop, WA and Bend, OR) are within 20 miles of the
        # trail and are included in the trail buffer.
        trail_buffer = USFS().buffer(distance=20)
        towns = Towns().boundaries()
        union = pd.concat([trail_buffer, towns],
                          sort=False).geometry.unary_union

        # Create OSM extract around trail
        poly_text = util.multipolygon_to_osm_poly(union)
        with NamedTemporaryFile('w+', suffix='.poly') as tmp:
            # Write the .poly file
            tmp.write(poly_text)
            tmp.seek(0)

            # TODO: put intermediate extracts into a tmp directory
            for state in states:
                osm_path = self.raw_dir / f'{state}-latest.osm.pbf'
                new_path = self.raw_dir / f'{state}-pct.o5m'
                cmd = [
                    'osmconvert', osm_path, '--out-o5m', f'-B={tmp.name}', '>',
                    new_path
                ]
                cmd = ' '.join([str(x) for x in cmd])
                run(cmd, shell=True, check=True)

            cmd = 'osmconvert '
            for state in states:
                new_path = self.raw_dir / f'{state}-pct.o5m'
                cmd += f'{new_path} '
            new_path = self.raw_dir / f'pct.o5m'
            cmd += f'-o={new_path}'
            run(cmd, shell=True, check=True)

            # Now pct.o5m exists on disk and includes everything within a 20
            # mile buffer and all towns

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

    def buffer(self, distance: float = 20) -> gpd.GeoDataFrame:
        """Load cached buffer

        If the buffer doesn't yet exist, creates it and saves it to disk

        Args:
            distance: buffer radius in miles

        Returns:
            GeoDataFrame with buffer geometry
        """
        path = self.data_dir / 'pct' / 'polygon' / 'usfs' / f'buffer{distance}mi.geojson'
        if not path.exists():
            self._create_buffer(distance=distance)

        return gpd.read_file(path)

    def _create_buffer(self, distance: float = 20):
        """Create buffer around USFS pct track

        Args:
            distance: buffer radius in miles
        """
        trail = self.trail()
        buffer = geom.buffer(trail, distance=20, unit='mile')

        save_dir = self.data_dir / 'pct' / 'polygon' / 'usfs'
        save_dir.mkdir(parents=True, exist_ok=True)

        buffer.to_file(save_dir / f'buffer{distance}mi.geojson',
                       driver='GeoJSON')


class PolygonSource(DataSource):
    def __init__(self):
        super(PolygonSource, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon'
        self.url = None
        self.filename = None

    def downloaded(self) -> bool:
        files = [self.filename]
        return all((self.save_dir / f).exists() for f in files)

    def download(self):
        """Download polygon shapefile and intersect with PCT track
        """
        assert self.url is not None, 'self.url must be set'
        assert self.filename is not None, 'self.filename must be set'

        # Load the FeatureCollection into a GeoDataFrame
        r = requests.get(self.url)
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
        self.save_dir.mkdir(exist_ok=True, parents=True)
        intersection.to_file(self.save_dir / self.filename, driver='GeoJSON')

    def polygon(self) -> gpd.GeoDataFrame:
        """Load Polygon as GeoDataFrame
        """
        if self.downloaded():
            path = self.save_dir / self.filename
            polygon = gpd.read_file(path)
            return polygon

        raise ValueError('trails not yet downloaded')


class WildernessBoundaries(PolygonSource):
    def __init__(self):
        super(WildernessBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.url = 'http://www.wilderness.net/GIS/Wilderness_Areas.zip'
        self.filename = 'wilderness.geojson'


class NationalParkBoundaries(PolygonSource):
    def __init__(self):
        super(NationalParkBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.url = 'https://opendata.arcgis.com/datasets/b1598d3df2c047ef88251016af5b0f1e_0.zip?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%22%3A102100%7D'
        self.filename = 'nationalpark.geojson'


class NationalForestBoundaries(PolygonSource):
    def __init__(self):
        super(NationalForestBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.url = 'https://data.fs.usda.gov/geodata/edw/edw_resources/shp/S_USA.AdministrativeForest.zip'
        self.filename = 'nationalforest.geojson'


class StateBoundaries(PolygonSource):
    def __init__(self):
        super(StateBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.url = 'https://www2.census.gov/geo/tiger/TIGER2017//STATE/tl_2017_us_state.zip'
        self.filename = 'state.geojson'


class CellTowers(DataSource):
    def __init__(self):
        super(CellTowers, self).__init__()
        self.save_dir = self.data_dir / 'raw' / 'cell_towers'
        self.save_dir.mkdir(parents=True, exist_ok=True)

        load_dotenv()
        self.api_key = os.getenv('OPENCELLID_API_KEY')
        assert self.api_key is not None, 'OpenCellID api key not loaded from .env'

        self.mccs = [302, 310, 311, 312, 313, 316]

    def download(self, overwrite=False):
        url = 'https://opencellid.org/ocid/downloads?token='
        url += f'{self.api_key}&type=mcc&file='
        for mcc in self.mccs:
            stub = f'{mcc}.csv.gz'
            if overwrite or (not (self.save_dir / stub).exists()):
                urlretrieve(url + stub, self.save_dir / stub)

    def download_mobile_network_codes(self):
        url = 'https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_3xx_(North_America)'
        # Get the Wikipedia table with a row that matches "Verizon Wireless"
        dfs = pd.read_html(url, match='Verizon Wireless')
        assert len(
            dfs) == 1, 'More than one match in wikipedia cell network tables'
        df = dfs[0]

        path = self.save_dir / 'network_codes.csv'
        df.to_csv(path, index=False)
