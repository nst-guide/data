# General downloads

import json
import math
import os
import re
from datetime import datetime
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
import rasterio
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fiona.io import ZipMemoryFile
from geopandas.tools import sjoin
from haversine import haversine
from lxml import etree as ET
from scipy.interpolate import interp2d
from shapely.geometry import LineString, Point, box, mapping, shape

import geom
import util
from grid import OneDegree, TenthDegree


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
        files = sorted(self.save_dir.glob('*/*.geojson'))
        return pd.concat([gpd.read_file(f) for f in files], sort=False)

    def associate_to_halfmile_section(self, trail_gdf=None):
        """For each town, find halfmile section that's closest to it
        """
        if trail_gdf is None:
            trail_gdf = Halfmile().trail_full(alternates=True)
        boundary_files = sorted(self.save_dir.glob('*/*.geojson'))

        for boundary_file in boundary_files:
            bound = gpd.read_file(boundary_file)
            tmp = trail_gdf.copy(deep=True)
            tmp['distance'] = trail_gdf.distance(bound.geometry[0])
            min_dist = tmp[tmp['distance'] == tmp['distance'].min()]

            # Deduplicate based on `section`; don't overcount the main trail and
            # a side trail, they have the same section id
            min_dist = min_dist.drop_duplicates('section')

            assert len(
                min_dist) <= 2, "Boundary has > 2 trails it's closest to"

            # If a town is touching two trail sections (like Belden), then just
            # pick one of them
            bound['section'] = min_dist['section'].iloc[0]
            # NOTE! This will overwrite town id's not sure how to stop that
            with open(boundary_file, 'w') as f:
                f.write(bound.to_json(show_bbox=True, indent=2))

    def _fix_town_ids(self):
        files = sorted(self.save_dir.glob('*/*.geojson'))
        for f in files:
            identifier = Path(f).stem
            name = ' '.join(s.capitalize() for s in identifier.split('_'))
            with open(f) as x:
                d = json.load(x)

            d['features'][0]['id'] = identifier
            d['features'][0]['properties']['id'] = identifier
            d['features'][0]['properties']['name'] = name

            with open(f, 'w') as x:
                json.dump(d, x, indent=2)


class OpenStreetMap(DataSource):
    """docstring for OpenStreetMap"""
    def __init__(self):
        super(OpenStreetMap, self).__init__()
        self.trail_ids = {'pct': 1225378}
        self.raw_dir = self.data_dir / 'raw' / 'osm'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        self.section_ids = {
            'CA_A': 1246902,
            'CA_B': 1246901,
            'CA_C': 1236787,
            'CA_D': 1238538,
            'CA_E': 1243366,
            'CA_F': 1243414,
            'CA_G': 1243679,
            'CA_H': 1244686,
            'CA_I': 1245492,
            'CA_J': 1246906,
            'CA_K': 1247934,
            'CA_L': 1249228,
            'CA_M': 1249245,
            'CA_N': 1251009,
            'CA_O': 1253065,
            'CA_P': 1253310,
            'CA_Q': 1255154,
            'CA_R': 1255155,
            'OR_B': 1258061,
            'OR_C': 1260310,
            'OR_D': 1260388,
            'OR_E': 1260401,
            'OR_F': 1268073,
            'OR_G': 1268116,
            'WA_H': 1285294,
            'WA_I': 1285818,
            'WA_J': 1296807,
            'WA_K': 1304995,
            'WA_L': 1322978
        }

    def _get_ways_for_relation(self, relation_id):
        url = f'https://www.openstreetmap.org/api/0.6/relation/{relation_id}'
        r = requests.get(url)
        soup = BeautifulSoup(r.text)
        members = soup.find_all('member')
        way_ids = [int(x['ref']) for x in members if x['type'] == 'way']
        return way_ids

    def _download_state_extracts(self, states, overwrite=False):
        """Download state-level OSM extracts from geofabrik
        """
        for state in states:
            osm_path = self.raw_dir / f'{state}-latest.osm.pbf'
            url = f'http://download.geofabrik.de/north-america/us/{state}-latest.osm.pbf'
            if overwrite or (not osm_path.exists()):
                urlretrieve(url, osm_path)

    def create_extracts(self):
        """Creates .o5m file for buffer area around trail
        """
        states = ['california', 'oregon', 'washington']
        self._download_state_extracts(states, overwrite=False)

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
        self.line_dir = self.data_dir / 'pct' / 'line' / 'halfmile'
        self.line_dir.mkdir(parents=True, exist_ok=True)
        self.point_dir = self.data_dir / 'pct' / 'point' / 'halfmile'
        self.point_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.data_dir / 'raw' / 'halfmile'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, overwrite=False):
        """Download Halfmile tracks and waypoints
        """
        states = ['ca', 'or', 'wa']
        headers = {
            'User-Agent':
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36',
        }

        # First just download the zip files to the raw directory
        for state in states:
            url = 'https://www.pctmap.net/wp-content/uploads/pct/'
            url += f'{state}_state_gps.zip'

            local_path = self.raw_dir / Path(url).name
            if overwrite or (not local_path.exists()):
                # Use requests instead of urlretrieve because of the need to
                # pass a user-agent
                r = requests.get(url, headers=headers)
                with open(local_path, 'wb') as f:
                    f.write(r.content)

        # Use these cached zip files to extract tracks and waypoints
        for state in states:
            with ZipFile(self.raw_dir / f'{state}_state_gps.zip') as z:
                names = [x for x in z.namelist() if '__MACOSX' not in x]
                trk_names = sorted([x for x in names if 'tracks' in x])
                for trk_name in trk_names:
                    fc = self._parse_track_gpx(z.read(trk_name))
                    path = Path(trk_name).stem + '.geojson'
                    with open(self.line_dir / path, 'w') as f:
                        geojson.dump(fc, f)

                wpt_names = sorted([x for x in names if 'waypoints' in x])
                for wpt_name in wpt_names:
                    fc = self._parse_waypoints_gpx(z.read(wpt_name))
                    path = Path(wpt_name).stem + '.geojson'
                    with open(self.point_dir / path, 'w') as f:
                        geojson.dump(fc, f)

    def _parse_track_gpx(self, b):
        gpx = gpxpy.parse(b.decode('utf-8'))

        name_re = re.compile(r'^((?:CA|OR|WA) Sec [A-Z])(?: - (.+))?$')

        features = []
        for track in gpx.tracks:
            assert len(track.segments) == 1, 'More than 1 segment in GPX track'

            l = LineString([(x.longitude, x.latitude, x.elevation)
                            for x in track.segments[0].points])

            section_name, alt_name = name_re.match(track.name).groups()
            name = alt_name if alt_name else section_name
            alternate = bool(alt_name)
            properties = {'name': name, 'alternate': alternate}
            features.append(geojson.Feature(geometry=l, properties=properties))

        return geojson.FeatureCollection(features)

    def _parse_waypoints_gpx(self, b):
        gpx = gpxpy.parse(b.decode('utf-8'))
        features = []
        for wpt in gpx.waypoints:
            pt = Point(wpt.longitude, wpt.latitude, wpt.elevation)
            properties = {
                'name': wpt.name,
                'description': wpt.description,
                'symbol': wpt.symbol,
            }
            features.append(geojson.Feature(geometry=pt,
                                            properties=properties))

        return geojson.FeatureCollection(features)

    def bbox_iter(self):
        """Get bounding box of each section
        """
        for section_name, gdf in self.trail_iter(alternates=True):
            yield section_name, gdf.unary_union.bounds

    @property
    def trk_geojsons(self):
        return sorted(self.line_dir.glob('*.geojson'))

    def _get_section(self, geojson_fname):
        # parse filename to get section
        sect_regex = re.compile(r'^(CA|OR|WA)_Sec_([A-Z])')
        state, letter = sect_regex.match(geojson_fname.stem).groups()
        section_id = f'{state}_{letter}'
        return section_id

    def _add_section_to_gdf(self, gdf, geojson_fname):
        section = self._get_section(geojson_fname)
        gdf['section'] = section
        return gdf

    def trail_iter(self, alternates=True):
        """Iterate over sorted trail sections
        """
        for f in self.trk_geojsons:
            gdf = gpd.read_file(f)
            section = self._get_section(f)
            gdf['section'] = section

            if not alternates:
                gdf = gdf[~gdf['alternate']]
            yield (section, gdf.to_crs(epsg=4326))

    def trail_full(self, alternates=True) -> gpd.GeoDataFrame:
        """Get Halfmile trail as GeoDataFrame
        """
        gdfs = []
        for f in self.trk_geojsons:
            gdf = gpd.read_file(f)
            gdf = self._add_section_to_gdf(gdf, f)
            gdfs.append(gdf)

        gdf = pd.concat(gdfs)
        if not alternates:
            gdf = gdf[~gdf['alternate']]

        return gdf.to_crs(epsg=4326)

    @property
    def wpt_geojsons(self):
        return sorted(self.point_dir.glob('*.geojson'))

    def wpt_iter(self):
        for f in self.wpt_geojsons:
            gdf = gpd.read_file(f)
            section = self._get_section(f)
            gdf['section'] = section
            yield (section, gdf.to_crs(epsg=4326))

    def wpt_full(self):
        gdfs = []
        for f in self.wpt_geojsons:
            gdf = gpd.read_file(f)
            gdf = self._add_section_to_gdf(gdf, f)
            gdfs.append(gdf)

        return pd.concat(gdfs).to_crs(epsg=4326)


class USFS(DataSource):
    """docstring for USFS"""
    def __init__(self):
        super(USFS, self).__init__()
        self.raw_dir = self.data_dir / 'raw' / 'usfs'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def downloaded(self) -> bool:
        save_dir = self.data_dir / 'pct' / 'line' / 'usfs'
        files = ['trail.geojson']
        return all((save_dir / f).exists() for f in files)

    def download(self, overwrite=False):
        url = 'https://www.fs.usda.gov/Internet/FSE_DOCUMENTS/stelprdb5332131.zip'
        local_path = self.raw_dir / Path(url).name
        if overwrite or (not local_path.exists()):
            urlretrieve(url, local_path)

        with open(local_path, 'rb') as f:
            with ZipMemoryFile(f.read()) as z:
                with z.open('PacificCrestTrail.shp') as collection:
                    crs = collection.crs
                    fc = list(collection)

        gdf = gpd.GeoDataFrame.from_features(fc, crs=crs)
        gdf = gdf.to_crs(epsg=4326)

        save_dir = self.data_dir / 'pct' / 'line' / 'usfs'
        save_dir.mkdir(parents=True, exist_ok=True)
        gdf.to_file(save_dir / 'trail.geojson', driver='GeoJSON')

    def trail(self) -> gpd.GeoDataFrame:
        """Load trail into GeoDataFrame"""
        save_dir = self.data_dir / 'pct' / 'line' / 'usfs'
        return gpd.read_file(save_dir / 'trail.geojson').to_crs(epsg=4326)

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


class GPSTracks(DataSource):
    def __init__(self):
        super(GPSTracks, self).__init__()

    def convert_fit_to_geojson(self):
        """
        The raw files of these GPS tracks are stored in the Git repository, but
        they still need to be converted into a helpful format.

        There doesn't appear to be a great Python package to work with .fit
        files, so I'm using [GPSBabel][gpsbabel] to do the conversion.

        [gpsbabel]: https://www.gpsbabel.org
        """

        gpsbabel_path = '/Applications/GPSBabelFE.app/Contents/MacOS/gpsbabel'
        raw_dir = self.data_dir / 'raw' / 'tracks'

        for fit_file in raw_dir.glob('*.fit'):
            geojson_path = fit_file.parents[0] / (fit_file.stem + '.geojson')
            cmd = [
                gpsbabel_path, '-i', 'garmin_fit', '-f',
                str(fit_file), '-o', 'geojson', '-F',
                str(geojson_path)
            ]
            run(cmd, check=True)

            gpx_path = fit_file.parents[0] / (fit_file.stem + '.gpx')
            cmd = [
                gpsbabel_path, '-i', 'garmin_fit', '-f',
                str(fit_file), '-o', 'gpx', '-F',
                str(gpx_path)
            ]
            run(cmd, check=True)

        # Now join all of these together
        features = []
        for geojson_file in raw_dir.glob('*.geojson'):
            with open(geojson_file) as f:
                d = geojson.load(f)

            features.extend(d['features'])

        fc = geojson.FeatureCollection(features)
        save_dir = self.data_dir / 'pct' / 'line' / 'gps_track'
        save_dir.mkdir(exist_ok=True, parents=True)
        with open(save_dir / 'gps_track.geojson', 'w') as f:
            geojson.dump(fc, f)

    def trail(self):
        gdf = gpd.read_file(self.data_dir / 'pct' / 'line' / 'gps_track' /
                            'gps_track.geojson')
        return gdf


class PolygonSource(DataSource):
    def __init__(self):
        super(PolygonSource, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon'
        self.url = None
        self.filename = None

    def downloaded(self) -> bool:
        files = [self.filename]
        return all((self.save_dir / f).exists() for f in files)

    def download(self, trail: gpd.GeoDataFrame, overwrite=False):
        """Download polygon shapefile and intersect with PCT track
        """
        assert self.url is not None, 'self.url must be set'
        assert self.filename is not None, 'self.filename must be set'

        if self.downloaded() or (not overwrite):
            return

        # Load the FeatureCollection into a GeoDataFrame
        r = requests.get(self.url)
        with fiona.BytesCollection(bytes(r.content)) as f:
            crs = f.crs
            gdf = gpd.GeoDataFrame.from_features(f, crs=crs)

        # Reproject to WGS84
        gdf = gdf.to_crs(epsg=4326)

        # Load Halfmile track for intersections
        trail = Halfmile().trail_full(alternates=True)
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
    """
    References:
    http://wiki.opencellid.org/wiki/Menu_map_view#database
    """
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


class LightningCounts(DataSource):
    """

    NOAA publishes daily counts of lightning strikes within .1-degree lat/lon
    grid cells.
    https://www.ncdc.noaa.gov/data-access/severe-weather/lightning-products-and-services

    """
    def __init__(self):
        super(LightningCounts, self).__init__()
        self.save_dir = self.data_dir / 'raw' / 'lightning'
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def downloaded(self) -> bool:
        return False

    def download(self, overwrite=False):
        url = 'https://www1.ncdc.noaa.gov/pub/data/swdi/database-csv/v2/'
        for year in range(1986, 2019):
            stub = f'nldn-tiles-{year}.csv.gz'
            if overwrite or (not (self.save_dir / stub).exists()):
                urlretrieve(url + stub, self.save_dir / stub)

    def read_data(self, year) -> pd.DataFrame:
        """Read lightning data and return daily count for PCT cells
        """
        stub = f'nldn-tiles-{year}.csv.gz'
        df = pd.read_csv(self.save_dir / stub, compression='gzip', skiprows=2)
        rename_dict = {
            '#ZDAY': 'date',
            'CENTERLON': 'lon',
            'CENTERLAT': 'lat',
            'TOTAL_COUNT': 'count'
        }
        df = df.rename(columns=rename_dict)
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        # Keep only the cells intersecting the trail
        # TODO: take the following get_cells() outside of this function because
        # it's slow
        centerpoints = TenthDegree().get_cells()
        center_df = pd.DataFrame(centerpoints, columns=['lon', 'lat'])

        merged = df.merge(center_df, how='inner')
        return merged


class Transit(DataSource):
    def __init__(self):
        super(Transit, self).__init__()

        self.routes = {}
        self.nearby_stops = {}
        self.all_stops = {}
        self.operators = {}

    def download(self, trail: gpd.GeoDataFrame):
        """Create trail-relevant transit dataset from transit.land database
        """
        # Find operators that intersect trail
        trail_line = trail.unary_union
        operators_near_trail = self.get_operators_near_trail()

        # For each operator, see if there are actually transit stops within a
        # walkable distance from the trail (currently set to 1000m)
        for operator in operators_near_trail:
            # First, see if this operator actually has stops near the trail
            stops = self.get_stops_near_trail(operator['onestop_id'],
                                              distance=1000)
            if len(stops) == 0:
                continue

            for stop in stops:
                # Add stop to the self.nearby_stops dict
                stop_id = stop['onestop_id']
                self.nearby_stops[stop_id] = stop

                # Get more info about each route that stops at stop
                # Routes are added to self.routes
                self.get_routes_for_stop(stop)

        self.update_stop_information()
        # self.get_schedules()

        # Serialize everything to disk
        save_dir = self.data_dir / 'pct' / 'line' / 'transit'
        save_dir.mkdir(parents=True, exist_ok=True)

        with open(save_dir / 'routes.json', 'w') as f:
            json.dump(self.routes, f)
        with open(save_dir / 'nearby_stops.json', 'w') as f:
            json.dump(self.nearby_stops, f)
        with open(save_dir / 'all_stops.json', 'w') as f:
            json.dump(self.all_stops, f)

    def get_operators_near_trail(self, trail_line: LineString):
        """Find transit operators with service area crossing the trail

        Using the transit.land API, you can find all transit operators within a
        bounding box. Since the bbox of the PCT is quite large, I then check the
        service area polygon of each potential transit operator to see if it
        intersects the trail.
        """
        trail_bbox = trail_line.bounds
        trail_bbox = [str(x) for x in trail_bbox]

        url = 'https://transit.land/api/v1/operators'
        params = {'bbox': ','.join(trail_bbox), 'per_page': 10000}
        r = requests.get(url, params=params)
        d = r.json()

        operators_on_trail = []
        for operator in d['operators']:
            # Check if the service area of the operator intersects trail
            operator_polygon = shape(operator['geometry'])
            intersects_trail = trail_line.intersects(operator_polygon)
            if intersects_trail:
                operators_on_trail.append(operator)

        return operators_on_trail

    def get_stops_near_trail(self,
                             trail_line: LineString,
                             operator_id,
                             distance=1000):
        """Find all stops in Transitland database that are near trail

        Args:
            operator_id: onestop operator id
            distance: distance to trail in meters
        """
        url = 'https://transit.land/api/v1/stops'
        params = {'served_by': operator_id, 'per_page': 10000}
        r = requests.get(url, params=params)
        d = r.json()

        stops_near_trail = []
        for stop in d['stops']:
            point = shape(stop['geometry'])
            nearest_trail_point = trail_line.interpolate(
                trail_line.project(point))

            dist = haversine(*point.coords,
                             *nearest_trail_point.coords,
                             unit='m')
            if dist < distance:
                stop['distance_to_trail'] = dist
                stops_near_trail.append(stop)

        return stops_near_trail

    def get_routes_for_stop(self, stop):
        for route_serving_stop in stop['routes_serving_stop']:
            route_onestop_id = route_serving_stop['route_onestop_id']
            url = f'https://transit.land/api/v1/onestop_id/{route_onestop_id}'
            if self.routes.get(route_onestop_id) is None:
                r = requests.get(url)
                d = r.json()
                self.routes[route_onestop_id] = d
                route_stops = d['stops_served_by_route']

                # Initialize keys in self.stops to fill in later with full stop
                # information
                for route_stop in route_stops:
                    route_stop_id = route_stop['stop_onestop_id']
                    self.all_stops[route_stop_id] = self.all_stops.get(
                        route_stop_id)

    def update_stop_information(self):
        """Update stop information from Transit land

        Stops are initialized by key in `get_routes_for_stop` but have no data.
        Fill in that data here.
        """
        for stop_id, value in self.all_stops.items():
            if value is not None:
                continue

            url = f'https://transit.land/api/v1/onestop_id/{stop_id}'
            r = requests.get(url)
            self.all_stops[stop_id] = r.json()

    def get_schedules(self):
        """Get schedules to add to route and stop data

        TODO figure out the best way to collect and store this
        """
        url = 'https://transit.land/api/v1/schedule_stop_pairs'
        for route_id in self.routes.keys():
            params = {'route_onestop_id': route_id, 'per_page': 10000}
            r = requests.get(url, params=params)
            d = r.json()

    def get_geojson_for_routes(self):
        """Create FeatureCollection from self.routes for inspection
        """
        features = []
        for route_id, route in self.routes.items():
            properties = {
                'onestop_id': route['onestop_id'],
                'name': route['name'],
                'vehicle_type': route['vehicle_type'],
                'operated_by_name': route['operated_by_name'],
            }
            feature = geojson.Feature(geometry=route['geometry'],
                                      properties=properties)
            features.append(feature)
        geojson.FeatureCollection(features)


class NationalElevationDataset(DataSource):
    """
    I compared these interpolated elevations with those contained in the
    Halfmile data for Sec A and the mean difference in elevation per point. 90%
    less than 5 meter difference.

    No interpolation        Linear interpolation:   Cubic with num_buffer=2
    count    1987.000000    count    1987.000000    count    1987.000000
    mean        1.964173    mean        1.778928    mean        1.776176
    std         2.188573    std         2.187626    std         2.227961
    min         0.000249    min         0.000076    min         0.000052
    25%         0.408596    25%         0.224535    25%         0.193832
    50%         1.192173    50%         0.834920    50%         0.756697
    75%         2.861689    75%         2.745461    75%         2.795144
    max        20.888750    max        19.116444    max        19.576745
    dtype: float64          dtype: float64          dtype: float64
    """
    def __init__(self):
        super(NationalElevationDataset, self).__init__()

        self.raw_dir = self.data_dir / 'raw' / 'elevation'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, trail, overwrite: bool = False):
        """Download 1/3 arc-second elevation data

        Args:
            overwrite: whether to overwrite existing files. If False, only
                downloads new copy if neither the ZIP file or extracted IMG file
                already exist.

        NOTE: some urls are different. I.e. for n37w119, the filename is
        n37w119.zip, not USGS_NED_13_n37w119_IMG.zip. Apparently this data was
        published in 2013, not 2018, which is why it has a different name. I
        haven't implemented a way to check this automatically yet.
        """
        urls = sorted(self._get_download_urls(trail=trail))
        for url in urls:
            # 50th degree latitudes is outside the US
            if 'n50w121' in url:
                continue

            save_path = self.raw_dir / (Path(url).stem + '.zip')
            extracted_path = self.raw_dir / (Path(url).stem + '.img')
            if overwrite or (not save_path.exists()
                             and not extracted_path.exists()):
                urlretrieve(url, save_path)

    def _get_download_urls(self, trail):
        """Create download urls
        """
        intersecting_bboxes = OneDegree().get_cells(trail)

        # The elevation datasets are identified by the _UPPER_ latitude and
        # _LOWER_ longitude, i.e. max and min repsectively
        baseurl = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation'
        baseurl += '/13/IMG/'
        urls = []
        for bbox in intersecting_bboxes:
            lat = str(int(bbox.bounds[3]))
            lon = str(int(abs(bbox.bounds[0])))
            url = baseurl + f'USGS_NED_13_n{lat}w{lon}_IMG.zip'
            urls.append(url)

        return urls

    def files(self, ext):
        return sorted(self.raw_dir.glob(f'*IMG{ext}'))

    def extract(self):
        """Unzip elevation ZIP files

        Only extract .img file from ZIP file to keep directory clean
        """
        zip_fnames = self.files('.zip')
        for zip_fname in zip_fnames:
            img_name = zip_fname.stem + '.img'
            out_dir = zip_fname.parents[0]
            cmd = ['unzip', '-o', zip_fname, img_name, '-d', out_dir]
            run(cmd, check=True)

    def query(self,
              lon: float,
              lat: float,
              num_buffer: int = 1,
              interp_kind: str = 'linear') -> float:
        """Query elevation data for given point

        NOTE: if you want to interpolate over neighboring squares, you can
        expand then window when reading, then get the actual xy position as lat
        lon, then get the neighboring positions as lat lon too

        Args:
            lon: longitude
            lat: latitude
            num_buffer: number of bordering cells around (lon, lat) to use when interpolating
            interp_kind: kind of interpolation. Passed to scipy.interpolate.interp2d. Can be ['linear’, ‘cubic’, ‘quintic']

        Returns elevation for point (in meters)
        """
        # Find file given lon, lat
        s = f'n{int(abs(math.ceil(lat)))}w{int(abs(math.floor(lon)))}'
        fname = [x for x in self.files('.img') if s in str(x)]
        assert len(fname) == 1, 'More than one elevation file matched query'
        fname = fname[0]

        # Read metadata of file
        dataset = rasterio.open(fname)

        # Find x, y of elevation square inside raster
        x, y = dataset.index(lon, lat)

        # Make window include cells around it
        # The number of additional cells depends on the value of num_buffer
        # When num_buffer==1, an additional 8 cells will be loaded and
        # interpolated on;
        # When num_buffer==2, an additional 24 cells will be loaded and
        # interpolated on, etc.
        # When using kind='linear' interpolation, I'm not sure if having the
        # extra cells makes a difference; ie if it creates the plane based only
        # on the closest cells or from all. When using kind='cubic', it's
        # probably more accurate with more cells.

        minx = x - num_buffer if x >= num_buffer else x
        maxx = x + num_buffer if x + num_buffer <= dataset.width else x
        miny = y - num_buffer if y >= num_buffer else y
        maxy = y + num_buffer if y + num_buffer <= dataset.width else y

        # Add +1 to deal with range() not including end
        maxx += 1
        maxy += 1

        window = ([minx, maxx], [miny, maxy])
        val_arr = dataset.read(1, window=window)

        msg = 'array has too few or too many values'
        max_num = 2 * num_buffer + 1
        assert (1 <= val_arr.shape[0] <= max_num) and (1 <= val_arr.shape[1] <=
                                                       max_num), msg

        # Now linearly interpolate
        # Get actual lat/lons
        # Note that zipping together means that I get the diagonal, i.e. one of
        # each of x, y. Since these aren't projected coordinates, but rather the
        # original lat/lons, this is a regular grid and this is ok.
        lonlats = [
            dataset.xy(x, y)
            for x, y in zip(range(minx, maxx), range(miny, maxy))
        ]
        lons = [x[0] for x in lonlats]
        lats = [x[1] for x in lonlats]

        fun = interp2d(x=lons, y=lats, z=val_arr, kind=interp_kind)
        value = fun(lon, lat)
        return value[0]


class USGSHydrography(DataSource):
    def __init__(self):
        super(USGSHydrography, self).__init__()
        self.raw_dir = self.data_dir / 'raw' / 'hydrology'
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.hu2_list = [16, 17, 18]
        self.trail = Halfmile().trail(alternates=True)

    def download(self, trail: gpd.GeoDataFrame, overwrite=False):
        self._download_boundaries(overwrite=overwrite)
        self._download_nhd(trail=trail, overwrite=overwrite)

    def load_nhd_iter(self) -> str:
        """Iterator to load NHD data for polygons that intersect the trail

        For now, this just yields the _path_ to the file, instead of the opened
        file, because I can only open a single layer of the GDB at a time, and
        I'll probably want more than one layer.
        """
        # Get all files in the raw hydrography folder conforming to NHD HU8 file
        # name
        # NOTE: If in the future I add more trails, this won't be performant,
        # because it could be trying to match PCT water boundaries to another
        # trail.
        name_regex = re.compile(r'^NHD_H_\d{8}_HU8_GDB.zip$')
        nhd_files = [
            path for path in self.raw_dir.iterdir()
            if name_regex.search(path.name)
        ]
        for f in nhd_files:
            yield f

    def _download_boundaries(self, overwrite):
        """
        Hydrologic Units range from 1-18. The PCT only covers parts of 16, 17,
        and 18. For other trails you'd want to cover the entire US, then get
        boundaries from it.
        """
        baseurl = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/'
        baseurl += 'WBD/HU2/GDB/'
        for hu2_id in self.hu2_list:
            name = f'WBD_{hu2_id}_HU2_GDB.zip'
            url = baseurl + name
            path = self.raw_dir / name
            if overwrite or (not path.exists()):
                urlretrieve(url, path)

    def _download_nhd(self, trail: LineString, overwrite):
        """Download National Hydrography Dataset for trail
        """
        baseurl = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/'
        baseurl += 'NHD/HU8/HighResolution/GDB/'

        gdfs = self._get_HU8_units_for_trail(trail=trail)
        hu8_ids = gdfs['HUC8'].unique()

        for hu8_id in hu8_ids:
            name = f'NHD_H_{hu8_id}_HU8_GDB.zip'
            url = baseurl + name
            path = self.raw_dir / name
            if overwrite or (not path.exists()):
                urlretrieve(url, path)

    def _get_HU8_units_for_trail(self, trail):
        """Find HU8 units that trail intersects

        This allows to find the names of the NHD datasets that need to be downloaded
        """
        all_intersecting_hu8 = []
        for hu2_id in self.hu2_list:
            # Get subbasin/hu8 boundaries for this region
            hu8 = self._load_HU8_boundaries(hu2_id)

            # Reproject to WGS84
            hu8 = hu8.to_crs(epsg=4326)

            # Intersect with the trail
            # NOTE: Need to check this works again with trail passing through
            intersecting_hu8 = sjoin(hu8, trail, how='inner')

            # Append
            all_intersecting_hu8.append(intersecting_hu8)

        return pd.concat(all_intersecting_hu8)

    def _load_HU8_boundaries(self, hu2_id):
        """Load Subregion Watershed boundaries

        Watershed boundaries are split up by USGS into a hierarchy of smaller
        and smaller areas. In _download_boundaries, the watershed boundary
        dataset is downloaded for `HU2` (Region), which is the second-largest
        collection, behind the full national file.

        In order to download the minimum amount of data from the National
        Hydrology Dataset (NHD), I want to download those at the `HU8`
        (Subbasin) level, so that I'm not downloading data for areas far from
        the trail. (`HU8` is the smallest area files that exist for NHD.) So
        here, I'm just extracting the `HU8` boundaries from the larger `HU2`
        watershed boundary datasets.
        """

        name = f'WBD_{hu2_id}_HU2_GDB.zip'
        path = self.raw_dir / name
        layers = fiona.listlayers(str(path))
        assert 'WBDHU8' in layers, 'HU8 boundaries not in WBD dataset'

        return gpd.read_file(path, layer='WBDHU8')


class PCTWaterReport(DataSource):
    def __init__(self):
        super(PCTWaterReport, self).__init__()

        load_dotenv()
        self.google_api_key = os.getenv('GOOGLE_SHEETS_API_KEY')
        assert self.google_api_key is not None, 'Google API Key missing'

        self.waypoints = gpd.read_file(self.data_dir / 'pct' / 'point' /
                                       'halfmile' / 'waypoints.geojson')
        self.waypoint_names = self.waypoints['name'].unique()

    def download(self, overwrite=False):
        """Download PCT Water report spreadsheets

        For now, since I can't get the Google Drive API to work, you have to
        download the folder manually from Google Drive. If you right click on
        the folder, you can download the entire archive at once.

        Put the downloaded ZIP file at data/raw/pctwater/pctwater.zip
        """
        pass

    def import_files(self):
        """Import water reports into a single DataFrame
        """
        raw_dir = self.data_dir / 'raw' / 'pctwater'
        z = ZipFile(raw_dir / 'pctwater.zip')
        names = z.namelist()
        names = sorted([x for x in names if 'snow' not in x.lower()])

        date_re = r'(20\d{2}-[0-3]\d-[0-3]\d)( [0-2]\d_[0-6]\d_[0-6]\d)?'

        dfs = []
        for n in names:
            date_match = re.search(date_re, n)
            if date_match:
                if date_match.group(1) == '2011-30-12':
                    fmt = '%Y-%d-%m'
                else:
                    fmt = '%Y-%m-%d'
                file_date = datetime.strptime(date_match.group(1), fmt)
            else:
                file_date = datetime.now()

            # Read all sheets of Excel workbook into list
            _dfs = pd.read_excel(z.open(n), header=None, sheet_name=None)
            for df in _dfs.values():
                df = self._clean_dataframe(df)
                if df is not None:
                    dfs.append([file_date, df])

        single_df = pd.concat([x[1] for x in dfs], sort=False)
        single_df.to_csv(raw_dir / 'single.csv')

    def _clean_dataframe(self, df):
        # TODO: merge with waypoint data to get stable lat/lon positions

        # In 2017, a sheet in the workbook is for snow reports
        if df.iloc[0, 0] == 'Pacific Crest Trail Snow & Ford Report':
            return None

        df = self._assemble_df_with_named_columns(df)
        df = self._resolve_df_names(df)

        # column 'map' should meet the map regex
        # Keep only rows that meet regex
        map_col_regex = re.compile(r'^[A-Z][0-9]{,2}$')
        df = df[df['map'].str.match(map_col_regex).fillna(False)]

        df = self._split_report_rows(df)
        return df

    def _resolve_df_names(self, df):
        """
        Columns should be
        [map, mile, waypoint, location, report, date, reported by, posted]
        """
        # To lower case
        df = df.rename(mapper=lambda x: x.lower(), axis='columns')

        # Rename any necessary columns
        rename_dict = {
            '2015 mile\nhalfmile app': 'mile_old',
            'old mile*': 'mile_old',
            'miles (nobo)': 'mile',
            'report ("-" means no report)': 'report'
        }
        df = df.rename(columns=rename_dict)

        should_be = [
            'map', 'mile', 'mile_old', 'waypoint', 'location', 'report',
            'date', 'reported by', 'posted'
        ]
        invalid_cols = set(df.columns).difference(should_be)
        if invalid_cols:
            raise ValueError(f'extraneous column {invalid_cols}')

        return df

    def _split_report_rows(self, df):
        """Split multiple reports into individual rows
        """
        # Remove empty report rows
        df = df[df['report'].fillna('').str.len() > 0]

        # Sometimes there's no data in the excel sheet, i.e. at the beginning of
        # the season
        if len(df) == 0:
            return None

        # Create new columns
        idx_cols = df.columns.difference(['report'])
        new_cols_df = pd.DataFrame(df['report'].str.split('\n').tolist())
        # name columns as report0, report1, report2
        new_cols_df = new_cols_df.rename(mapper=lambda col: f'report{col}',
                                         axis=1)

        # Append these new columns to full df
        assert len(df) == len(new_cols_df)
        df = pd.concat(
            [df.reset_index(drop=True),
             new_cols_df.reset_index(drop=True)],
            axis=1)
        assert len(df) == len(new_cols_df)

        # Remove original 'report' column
        df = df.drop('report', axis=1)

        # Melt from wide to long
        # Bug prevents working when date is a datetime dtype
        df['date'] = df['date'].astype(str)
        reshaped = pd.wide_to_long(df,
                                   stubnames='report',
                                   i=idx_cols,
                                   j='report_num')
        reshaped = reshaped.reset_index()
        # remove new j column
        reshaped = reshaped.drop('report_num', axis=1)
        # Remove extra rows created from melt
        reshaped = reshaped[~reshaped['report'].isna()]

        return reshaped

    def _assemble_df_with_named_columns(self,
                                        df: pd.DataFrame) -> pd.DataFrame:
        """Create DataFrame with named columns

        Column order changes across time in the water reports. Instead of
        relying solely on order, first remove the pre-header lines, attach
        labels, and reassemble as DataFrame.
        """
        column_names = None
        past_header = False
        rows = []
        for row in df.itertuples(index=False, name='Pandas'):
            # print(row)
            if str(row[0]).lower() == 'map':
                column_names = row
                past_header = True
                continue

            if not past_header:
                continue

            rows.append(row)

        if column_names is None:
            raise ValueError('column names not found')

        return pd.DataFrame.from_records(rows, columns=column_names)

    # def _list_google_sheets_files(self):
    #     """
    #     NOTE: was unable to get this to work. Each time I tried to list files, I got
    #     "Shared drive not found: 0B3jydhFdh1E2aVRaVEx0SlJPUGs"
    #     """
    #     from googleapiclient.discovery import build
    #     from google_auth_oauthlib.flow import InstalledAppFlow, Flow
    #
    #     client_secret_path = Path('~/.credentials/google_sheets_client_secret.json')
    #     client_secret_path = client_secret_path.expanduser().resolve()
    #
    #     flow = Flow.from_client_secrets_file(
    #         str(client_secret_path),
    #         scopes=['https://www.googleapis.com/auth/drive.readonly'],
    #         redirect_uri='urn:ietf:wg:oauth:2.0:oob')
    #
    #     # flow = InstalledAppFlow.from_client_secrets_file(
    #     #     str(client_secret_path),
    #     #     scopes=['drive', 'sheets'])
    #     auth_uri = flow.authorization_url()
    #     print(auth_uri[0])
    #
    #     token = flow.fetch_token(code='insert token from oauth screen')
    #     credentials = flow.credentials
    #
    #     # drive_service = build('drive', 'v3', developerKey=self.google_api_key)
    #     drive_service = build('drive', 'v3', credentials=credentials)
    #     results = drive_service.files().list(
    #         pageSize=10,
    #         q=("sharedWithMe"),
    #         driveId='0B3jydhFdh1E2aVRaVEx0SlJPUGs',
    #         includeItemsFromAllDrives=True,
    #         supportsAllDrives=True,
    #         corpora="drive",
    #         fields="*").execute()
    #     items = results.get('files', [])
    #     len(items)
