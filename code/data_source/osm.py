import re
from pathlib import Path
from subprocess import run
from tempfile import mkdtemp
from urllib.request import urlretrieve

import geojson
import requests
from bs4 import BeautifulSoup
from shapely.geometry import Polygon

import osmnx as ox
from constants import TRAIL_OSM_RELATION_XW, TRAIL_STATES_XW
from util import polygon_to_osm_poly

from .base import DataSource
from .halfmile import Halfmile


class OpenStreetMap(DataSource):
    """docstring for OpenStreetMap"""
    def __init__(self, trail_code, use_cache=True):
        super(OpenStreetMap, self).__init__()

        self.trail_code = trail_code
        self.trail_id = TRAIL_OSM_RELATION_XW.get(trail_code)
        if self.trail_id is None:
            raise ValueError('invalid trail_code')

        self.raw_dir = self.data_dir / 'raw' / 'osm'
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.geofabrik_dir = self.raw_dir / 'geofabrik'
        self.geofabrik_dir.mkdir(exist_ok=True, parents=True)
        self.session = requests.Session()
        self.use_cache = use_cache

    def download_geofabrik(self, overwrite=False):

        baseurl = 'https://download.geofabrik.de/north-america/us/'
        states = TRAIL_STATES_XW.get(self.trail_code)
        for stub in states:
            fname = stub + '-latest.osm.pbf'
            url = baseurl + fname
            local_path = self.geofabrik_dir / fname
            if overwrite or (not local_path.exists()):
                urlretrieve(url, str(local_path))

    def load_geofabrik(self, polygon):
        path = self._filter_geofabrik(polygon)
        return ox.graph_from_file(path, retain_all=True, simplify=False)

    def _filter_geofabrik(self, polygon):
        """Filter geofabrik files by polygon

        Note, for now this filters to include only highways. You could filter a
        different way type in the future.
        """
        # Create temp dir
        tmpdir = Path(mkdtemp())

        # Create and write out poly file
        poly_str = polygon_to_osm_poly(polygon)
        poly_path = tmpdir / 'extract.poly'
        with open(poly_path, 'w') as f:
            f.write(poly_str)

        # For each state, run osmconvert on that state using the .poly polygon
        states = TRAIL_STATES_XW.get(self.trail_code)
        extracted_paths = []
        for stub in states:
            fname_orig = stub + '-latest.osm.pbf'
            fname_new = stub + '-extract.o5m'

            orig_path = self.geofabrik_dir / fname_orig
            assert orig_path.exists(), 'geofabrik download does not exist'

            extracted_path = tmpdir / fname_new
            extracted_paths.append(extracted_path)

            cmd = [
                'osmconvert',
                str(orig_path),
                '--drop-author',
                '--complete-ways',
                f'-B={poly_path}',
                f'-o={str(extracted_path)}',
            ]
            run(cmd, check=True)

        # Now merge the extracts from each of the above states
        joined_path = tmpdir / 'joined.o5m'
        cmd = ['osmconvert']
        # input files
        cmd.extend(map(str, extracted_paths))
        # output file
        cmd.append(f'-o={str(joined_path)}')
        run(cmd, check=True)

        # Run osmfilter on this joined file to keep only highways
        filtered_path = tmpdir / 'filtered.osm'
        cmd = f'osmfilter --keep="highway=" {str(joined_path)} > {str(filtered_path)}'
        run(cmd, check=True, shell=True)

        return filtered_path

    def cache_section_graphs(self, overwrite=False, simplify=False):
        """Wrapper to download graphs for each section of trail

        This just calls self.get_ways_for_polygon for each section.
        """

        hm = Halfmile()
        for section_name, buf in hm.buffer_iter(distance=2, unit='mile'):
            print(f'Getting graph for section: {section_name}')
            self.get_ways_for_polygon(
                polygon=buf,
                section_name=section_name,
                overwrite=overwrite,
                simplify=simplify)
            print(f'Finished getting graph for section: {section_name}')

    def get_relation_ids_for_trail(self):
        """Get list of relation ids that make up trail sections

        Args:
            trail_code: standard trail code, e.g. `pct` or `at`

        Returns:
            List[str] of relation ids
        """
        relation = self._osm_api(relation=self.trail_id)
        members = relation.find_all('member')
        relations = [x for x in members if x.attrs['type'] == 'relation']
        return [x.attrs['ref'] for x in relations]

    def get_way_ids_for_relation(self, relation_id, alternates=None):
        """Get OSM way ids given relation id

        Args:
            relation_id: OSM relation id
            alternates: if None, returns all; if True, returns only alternates;
                if False returns only non-alternates

        Returns:
            - List[str] of way ids
        """
        relation = self._osm_api(relation=relation_id)
        members = relation.find_all('member')
        ways = [x for x in members if x.attrs['type'] == 'way']

        # Restrict members based on alternates setting
        if alternates is True:
            ways = [x for x in ways if x['role'] == 'alternate']
        elif alternates is False:
            ways = [x for x in ways if x['role'] != 'alternate']

        return [x.attrs['ref'] for x in ways]

    def get_way_ids_for_section(self, section_name, alternates=None):
        """Get OSM way ids given section name

        Args:
            section_name: canonical PCT section name, i.e. 'CA_A' or 'OR_C'
            alternates: if None, returns all; if True, returns only alternates;
                if False returns only non-alternates

        Returns:
            - list of integers representing way ids
        """
        section_ids = self.get_relation_ids_for_trail()

        section_infos = [
            self.get_info(relation=section_id) for section_id in section_ids
        ]
        section_info = [
            x for x in section_infos
            if x.get('short_name') == section_name.lower()
        ][0]

        return self.get_way_ids_for_relation(
            relation_id=section_info['id'], alternates=alternates)

    def get_node_ids_for_way(self, way_id):
        """Get OSM node ids given way id

        Args:
            - way_id: OSM way id

        Returns:
            - List[str] of node ids
        """
        way = self._osm_api(way=way_id)
        nodes = way.find_all('nd')
        return [x.attrs['ref'] for x in nodes]

    def get_info(self, relation=None, way=None, node=None):
        """Get info for given OSM id


        Returns:
            For relation:
            dict:
            {'name': 'PCT - California Section A',
             'short_name': 'CA_A',
             'network': 'rwn',
             'ref': 'PCT',
             'route': 'foot',
             'type': 'route',
             'wikidata': 'Q2003736',
             'wikipedia': 'en:Pacific Crest Trail',
             'id': 1246902}

        """
        if sum(map(bool, [relation, way, node])) > 1:
            raise ValueError('only one of relation, way, and node allowed')

        soup = self._osm_api(relation=relation, way=way, node=node)
        tags = {tag.attrs['k']: tag.attrs['v'] for tag in soup.find_all('tag')}
        tags['id'] = soup.attrs['id']

        if relation:
            # If the relation is a part of the PCT, generate a short name for
            # the section. I.e. the `name` is generally `PCT - California
            # Section A` and the short name would be `ca_a`
            if self.trail_code == 'pct':
                states = ['California', 'Oregon', 'Washington']
                regex_str = f"({'|'.join(states)})"
                regex_str += r'\s+Section\s+([A-Z])$'
                m = re.search(regex_str, tags['name'])
                if m:
                    short_name = (
                        f'{m.groups()[0][:2].upper()}_{m.groups()[1].upper()}')
                    tags['short_name'] = short_name.lower()

        if node:
            tags['lat'] = float(soup.attrs['lat'])
            tags['lon'] = float(soup.attrs['lon'])

        return tags

    def get_geojson_for_way(self, way_id):
        """Construct GeoJSON Feature with LineString geometry for way

        Args:
            - way_id: OSM way id

        Returns:
            geojson.Feature with LineString geometry of way
        """
        way_info = self.get_info(way=way_id)
        node_ids = self.get_node_ids_for_way(way_id)

        points = []
        for node_id in node_ids:
            node_info = self.get_info(node=node_id)
            points.append([node_info['lon'], node_info['lat']])

        line = geojson.LineString(points)
        return geojson.Feature(id=way_id, geometry=line, properties=way_info)

    def get_ways_for_polygon(
            self,
            polygon,
            section_name,
            source='geofabrik',
            way_types=['highway'],
            use_cache=True):
        """Retrieve graph of OSM nodes and ways for given polygon

        I tested out downloading more than just ways tagged "highway"; to also
        include railroads, power lines, and waterways. However osmnx only gives
        you intersections where there's an intersection in the original OSM
        data, so power lines don't have intersections because they don't cross
        at trail-height, and many water intersections are just missing.

        Because of this, I think the best way forward is to download "highway"
        and "railway" at first, then separately download power lines and use the
        NHD directly for streams.

        Args:
            - polygon: shapely polygon. Usually a buffer around trail, used to
              filter OSM data.
            - section_name: Name of section, i.e. 'CA_A' or 'OR_C'
            - source: either 'geofabrik' or 'overpass'. The former uses
              geofabrik downloads + osmconvert + osmfilter to more quickly get
              data extracts (after the initial Geofabrik data download). The
              latter uses the Overpass API through osmnx, which is considerably
              slower for large area requests.
            - way_types: names of OSM keys that are applied to ways that should
              be kept
            - use_cache: if True, attempts to use cached data. Only for
              source='overpass'

        Returns:
            - networkx/osmnx graph
        """
        fname = f"{section_name}_way_types={','.join(way_types)}.graphml"
        graphml_path = self.raw_dir / fname
        if use_cache and (source == 'overpass') and (graphml_path.exists()):
            return ox.load_graphml(graphml_path)

        if source == 'geofabrik':
            g = self.load_geofabrik(polygon)
        elif source == 'overpass':
            # Set osmnx configuration to download desired attributes of nodes and
            # ways
            useful_tags_node = ox.settings.useful_tags_node
            useful_tags_node.extend(['historic', 'wikipedia'])
            useful_tags_path = ox.settings.useful_tags_path
            useful_tags_path.extend(['surface', 'wikipedia'])
            useful_tags_path.extend(way_types)
            ox.config(
                useful_tags_node=useful_tags_node,
                useful_tags_path=useful_tags_path)

            # Get all ways, then restrict to ways of type `way_types`
            # https://github.com/gboeing/osmnx/issues/151#issuecomment-379491607
            g = ox.graph_from_polygon(
                polygon,
                simplify=False,
                clean_periphery=True,
                retain_all=True,
                network_type='all_private',
                truncate_by_edge=True,
                name=section_name,
                infrastructure='way')
        else:
            raise ValueError('source must be geofabrik or overpass')

        # strict=False is very important so that `osmid` in the resulting edges
        # DataFrame is never a List
        # Note: simplify_graph should come immediately after first creating the
        # graph. This is because once you start deleting some ways, there can be
        # empty nodes, and you get a KeyError when simplifying later. See:
        # https://github.com/gboeing/osmnx/issues/323
        g = ox.simplify_graph(g, strict=False)

        # Currently the graph g has every line ("way") in OSM in the area of
        # polygon. I only want the ways of type `way_types` that were provided
        # as an argument, so find all the other-typed ways and drop them
        if source == 'overpass':
            ways_to_drop = [(u, v, k)
                            for u, v, k, d in g.edges(keys=True, data=True)
                            if all(key not in d for key in way_types)]
            g.remove_edges_from(ways_to_drop)
            g = ox.remove_isolated_nodes(g)

        # Save graph object to cache
        ox.save_graphml(g, graphml_path)
        return g

    def get_town_pois_for_polygon(self, polygon: Polygon):
        """Get Point of Interests from OSM for polygon

        Note: this function requires https://github.com/gboeing/osmnx/pull/342
        to be merged. For now, I use my own fork.

        Args:
            - polygon: polygon to search within
            - poi_type: either 'town', 'trail', or None.
        """
        useful_tags_node = ox.settings.useful_tags_node
        useful_tags_node.extend([
            'historic', 'wikipedia', 'tourism', 'internet_access',
            'washing_machine', 'phone', 'website'
        ])
        ox.config(useful_tags_node=useful_tags_node)

        tags = {
            'amenity': [
                # Sustenance
                'bar',
                'biergarten',
                'cafe',
                'drinking_water',
                'fast_food',
                'ice_cream',
                'pub',
                'restaurant',
                # Financial
                'atm',
                'bank',
                # Healthcare
                'clinic',
                'hospital',
                'pharmacy',
                # Others
                'post_office',
                'ranger_station',
                'shower',
                'toilets',
            ],
            'shop': [
                # Food, beverages
                'bakery',
                'convenience',
                # General store, department store, mall
                'general',
                'supermarket',
                'wholesale',
                # Outdoors and sport, vehicles                '',
                'outdoor',
                'sports',
                # Others
                'laundry',
            ],
            'tourism': [
                'camp_site',
                'hostel',
                'hotel',
                'motel',
                'picnic_site',
            ],
        }  # yapf: ignore

        gdf = ox.create_poi_gdf(polygon=polygon, tags=tags)

        # Drop a couple columns
        keep_cols = [
            'osmid', 'geometry', 'name', 'amenity', 'tourism', 'shop',
            'website', 'cuisine', 'opening_hours', 'brand:wikidata',
            'internet_access', 'internet_access:fee', 'addr:housenumber',
            'addr:street', 'addr:unit', 'addr:city', 'addr:state',
            'addr:postcode'
        ]
        keep_cols = [x for x in keep_cols if x in gdf.columns]
        gdf = gdf.filter(items=keep_cols, axis=1)

        if len(gdf) == 0:
            return gdf

        # Keep only rows with a non-missing name
        if 'name' in gdf.columns:
            gdf = gdf.loc[gdf['name'].notna()]

        if len(gdf) == 0:
            return gdf

        # Some geometries are polygons, so replace geometry with its centroid.
        # For Points this makes no difference; for Polygons, this takes the
        # centroid.
        gdf.geometry = gdf.geometry.centroid

        return gdf

    def get_trail_pois_for_polygon(self, polygon: Polygon):
        useful_tags_node = ox.settings.useful_tags_node
        useful_tags_node.extend(
            ['historic', 'wikipedia', 'tourism', 'backcountry'])
        ox.config(useful_tags_node=useful_tags_node)

        tags = {
            'amenity': [
                'shelter',
                'shower',
                'toilets',
            ],
            'natural': [
                'peak',
                'saddle',
            ],
            'toilets:disposal': [
                'pitlatrine',
                'flush',
            ],
            'tourism': [
                'alpine_hut',
                'camp_site',
                'picnic_site',
                'viewpoint',
                'wilderness_hut',
            ],
        }  # yapf: ignore

        gdf = ox.create_poi_gdf(polygon=polygon, tags=tags)

        # Some geometries are polygons, so replace geometry with its centroid.
        # For Points this makes no difference; for Polygons, this takes the
        # centroid.
        gdf.geometry = gdf.geometry.centroid

        # TODO: keep only useful columns?
        return gdf

    def _osm_api(self, relation=None, way=None, node=None):
        url = 'https://www.openstreetmap.org/api/0.6/'
        if sum(map(bool, [relation, way, node])) > 1:
            raise ValueError('only one of relation, way, and node allowed')

        if relation:
            url += f'relation/{relation}'
        if way:
            url += f'way/{way}'
        if node:
            url += f'node/{node}'

        r = self.session.get(url)
        soup = BeautifulSoup(r.text, 'lxml')

        if relation:
            relations = soup.find_all('relation')
            assert len(relations) == 1
            return relations[0]
        if way:
            ways = soup.find_all('way')
            assert len(ways) == 1
            return ways[0]
        if node:
            nodes = soup.find_all('node')
            assert len(nodes) == 1
            return nodes[0]
