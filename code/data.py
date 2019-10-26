# General downloads

import json
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
import requests
from dotenv import load_dotenv
from fiona.io import ZipMemoryFile
from geopandas.tools import sjoin
from haversine import haversine
from lxml import etree as ET
from shapely.geometry import LineString, MultiLineString, box, mapping, shape
from shapely.ops import linemerge

import geom
import util
from grid import TenthDegree


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

    def download(self, overwrite=False):
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
        self.trail = USFS().trail().iloc[0].geometry

        self.routes = {}
        self.nearby_stops = {}
        self.all_stops = {}
        self.operators = {}

    def download(self):
        """Create trail-relevant transit dataset from transit.land database
        """

        # Find operators that intersect trail
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

    def get_operators_near_trail(self):
        """Find transit operators with service area crossing the trail

        Using the transit.land API, you can find all transit operators within a
        bounding box. Since the bbox of the PCT is quite large, I then check the
        service area polygon of each potential transit operator to see if it
        intersects the trail.
        """
        trail_bbox = self.trail.bounds
        trail_bbox = [str(x) for x in trail_bbox]

        url = 'https://transit.land/api/v1/operators'
        params = {'bbox': ','.join(trail_bbox), 'per_page': 10000}
        r = requests.get(url, params=params)
        d = r.json()

        operators_on_trail = []
        for operator in d['operators']:
            # Check if the service area of the operator intersects trail
            operator_polygon = shape(operator['geometry'])
            intersects_trail = self.trail.intersects(operator_polygon)
            if intersects_trail:
                operators_on_trail.append(operator)

        return operators_on_trail

    def get_stops_near_trail(self, operator_id, distance=1000):
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
            nearest_trail_point = self.trail.interpolate(
                self.trail.project(point))

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
