import re
from typing import List

import requests
from bs4 import BeautifulSoup
from shapely.geometry import Polygon

import osmnx as ox
from constants import TRAIL_OSM_RELATION_XW

from .base import DataSource
from .halfmile import Halfmile


class OpenStreetMap(DataSource):
    """docstring for OpenStreetMap"""
    def __init__(self):
        super(OpenStreetMap, self).__init__()
        self.trail_ids = TRAIL_OSM_RELATION_XW
        self.raw_dir = self.data_dir / 'raw' / 'osm'
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()

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

    def get_relations_for_trail(self, trail_code):
        """Get list of relations that make up sections within PCT

        Args:
            trail_code: standard trail code, e.g. `pct` or `at`

        Returns:
            dict: {'CA_A': 1234567, ...}
        """
        trail_id = self.trail_ids.get(trail_code)
        if trail_id is None:
            raise NotImplementedError('trail_code not defined')

        url = f'https://www.openstreetmap.org/api/0.6/relation/{trail_id}'
        r = self.session.get(url)
        soup = BeautifulSoup(r.text, 'lxml')
        relations = soup.find_all('relation')
        assert len(relations) == 1, 'more than one top-level relation object'
        relation = relations[0]

        members = relation.find_all('member')
        relations = [x for x in members if x.attrs['type'] == 'relation']
        sections = [self.get_relation_info(x.attrs['ref']) for x in relations]
        return {d['short_name']: d['id'] for d in sections}

    def get_alternates_for_trail(self, trail_code):
        """Get list of alternates within PCT

        Args:
            trail_id: relation for entire trail

        Returns:
            list: [{'bicycle': 'no',
                    'highway': 'path',
                    'horse': 'no',
                    'lit': 'no',
                    'name': 'Pacific Crest Trail (alternate)',
                    'ref': 'PCT alt.',
                    'surface': 'ground',
                    'id': 337321382},
                    ...
        """
        trail_id = self.trail_ids.get(trail_code)
        if trail_id is None:
            raise NotImplementedError('trail_code not defined')

        url = f'https://www.openstreetmap.org/api/0.6/relation/{trail_id}'
        r = self.session.get(url)
        soup = BeautifulSoup(r.text, 'lxml')
        relations = soup.find_all('relation')
        assert len(relations) == 1, 'more than one top-level relation object'

        # Alternates are `ways`
        members = relations[0].find_all('member')
        alternates = [x for x in members if x.attrs['role'] == 'alternate']
        msg = 'alternate not way type'
        assert all(x.attrs['type'] == 'way' for x in alternates), msg
        return [self.get_way_info(x.attrs['ref']) for x in alternates]

    def get_relation_info(self, relation_id):
        """Get metadata about relation_id

        Args:
            relation_id: OSM relation id

        Returns:
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
        url = f'https://www.openstreetmap.org/api/0.6/relation/{relation_id}'
        r = self.session.get(url)
        soup = BeautifulSoup(r.text, 'lxml')
        tags = {tag.attrs['k']: tag.attrs['v'] for tag in soup.find_all('tag')}

        # If the relation is a part of the PCT, generate a short name for the
        # section. I.e. the `name` is generally `PCT - California Section A` and
        # the short name would be `ca_a`
        if tags.get('ref') == 'PCT':
            states = ['California', 'Oregon', 'Washington']
            regex_str = f"({'|'.join(states)})"
            regex_str += r'\s+Section\s+([A-Z])$'
            m = re.search(regex_str, tags['name'])
            if m:
                short_name = (
                    f'{m.groups()[0][:2].upper()}_{m.groups()[1].upper()}')
                tags['short_name'] = short_name.lower()

        tags['id'] = int(soup.find('relation').attrs['id'])
        return tags

    def get_way_info(self, way_id):
        """Get metadata about way_id

        Args:
            way_id: OSM way id

        Returns:
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
        url = f'https://www.openstreetmap.org/api/0.6/way/{way_id}'
        r = self.session.get(url)
        soup = BeautifulSoup(r.text, 'lxml')
        tags = {tag.attrs['k']: tag.attrs['v'] for tag in soup.find_all('tag')}
        tags['id'] = int(soup.find('way').attrs['id'])
        return tags

    def get_node_info(self, node_id) -> dict:
        """Get OSM node information given node id

        Args:
            - node_id: OSM node id
        Given node id, get location and tags about node
        """
        url = f'https://www.openstreetmap.org/api/0.6/node/{node_id}'
        r = self.session.get(url)
        soup = BeautifulSoup(r.text, 'lxml')
        node = soup.find('node')
        d = node.attrs
        d.update({n.attrs['k']: n.attrs['v'] for n in node.find_all('tag')})
        return d

    def get_nodes_for_way(self, way_id) -> List[int]:
        """Get OSM node ids given way id

        Args:
            - way_id: OSM way id

        Returns:
            - list of integers representing node ids
        """
        url = f'https://www.openstreetmap.org/api/0.6/way/{way_id}'
        r = self.session.get(url)
        soup = BeautifulSoup(r.text, 'lxml')
        node_ids = [int(x['ref']) for x in soup.find_all('nd')]
        return node_ids

    def get_ways_for_polygon(
            self,
            polygon,
            section_name,
            way_types=['highway', 'railway'],
            overwrite=False):
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
            - polygon: buffer or bbox around trail, used to filter OSM data.
              Generally is a buffer of a section of trail, but a town boundary
              could also be passed.
            - section_name: Name of section, i.e. 'CA_A' or 'OR_C'
            - way_types: names of OSM keys that are applied to ways that should
              be kept
            - overwrite: if True, re-downloads data instead of using cached data

              For that reason, I think it's generally better to leave
              `simplify=False`, so that you don't have to deal with nested lists
              in the DataFrame.

        Returns:
            - osmnx graph
        """
        fname = f"{section_name}_way_types={','.join(way_types)}.graphml"
        graphml_path = self.raw_dir / fname
        if not overwrite and (graphml_path.exists()):
            return ox.load_graphml(graphml_path)

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
        ways_to_drop = [(u, v, k)
                        for u, v, k, d in g.edges(keys=True, data=True)
                        if all(key not in d for key in way_types)]
        g.remove_edges_from(ways_to_drop)
        g = ox.remove_isolated_nodes(g)

        ox.save_graphml(g, graphml_path)
        return g

    def get_way_ids_for_section(self, section_name,
                                alternates=False) -> List[int]:
        """Get OSM way ids given section name

        Args:
            section_name: canonical PCT section name, i.e. 'CA_A' or 'OR_C'
            alternates: whether to include ways designated role=alternate

        Returns:
            - list of integers representing way ids
        """
        section_ids = self.get_relations_within_pct(self.trail_ids['pct'])
        section_id = section_ids.get(section_name)
        if section_id is None:
            raise ValueError(f'invalid section name: {section_name}')

        return self.get_way_ids_for_relation(section_id, alternates=alternates)

    def get_way_ids_for_relation(self, relation_id,
                                 alternates=False) -> List[int]:
        """Get OSM way ids given relation id

        Args:
            relation_id: OSM relation id
            alternates: whether to include ways designated role=alternate

        Returns:
            - list of integers representing way ids
        """
        url = f'https://www.openstreetmap.org/api/0.6/relation/{relation_id}'
        r = self.session.get(url)
        soup = BeautifulSoup(r.text, 'lxml')
        members = soup.find_all('member')

        # Restrict members based on alternates setting
        if not alternates:
            members = [x for x in members if x['role'] != 'alternate']

        way_ids = [int(x['ref']) for x in members if x['type'] == 'way']
        return way_ids

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
