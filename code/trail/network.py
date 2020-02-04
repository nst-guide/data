import networkx as nx

import constants
import geom
import osmnx as ox
from data_source import OpenStreetMap

from .util import approx_trail


class TrailNetwork(object):
    """TrailNetwork
    """
    def __init__(
            self,
            trail_code,
            trail_section=None,
            trail_alternates=False,
            buffer_dist=2,
            buffer_unit='mi'):
        """TrailNetwork

        Args:
            - trail_code: code for trail, e.g. 'pct' or 'at'
            - trail_section: section of trail, e.g. 'ca_south'
            - trail_alternates: include alternates
            - buffer_dist: distance used for buffer when getting trail network
              from OSM
            - buffer_unit: unit used for buffer when getting trail network from
              OSM
        """
        super(TrailNetwork, self).__init__()

        if trail_code != 'pct':
            raise ValueError('invalid trail code')

        self.trail_code = trail_code
        self.crs = constants.TRAIL_EPSG_XW[trail_code]

        self.trail_section = trail_section
        self.trail_alternates = trail_alternates
        self.buffer_dist = buffer_dist
        self.buffer_unit = buffer_unit

        # Get approximate trail geometry
        # This is passed to osmnx/Overpass API to quickly get all roads/trails
        # in the area.
        self.approx_trail_gdf = approx_trail(
            self.trail_code,
            trail_section=trail_section,
            alternates=trail_alternates)

        self.osm = OpenStreetMap(trail_code)

        self.G = self.get_osm_network(
            buffer_dist=buffer_dist, buffer_unit=buffer_unit)

    def get_osm_network(self, buffer_dist, buffer_unit, use_cache=True):
        """Use osmnx to get network of roads/trails around trail geometry
        """
        # Take buffer of approximate trail
        approx_trail_buffer_gdf = geom.buffer(
            self.approx_trail_gdf,
            distance=buffer_dist,
            unit=buffer_unit,
            crs=self.crs)

        # Consolidate GeoDataFrame to shapely geometry
        approx_trail_buffer = approx_trail_buffer_gdf.unary_union

        # Get graph
        G = self.osm.get_ways_for_polygon(
            polygon=approx_trail_buffer,
            section_name=self.trail_section,
            source='geofabrik',
            use_cache=use_cache)

        # Get way ids that are part of the trail
        trail_way_ids = self._get_osm_way_ids_for_trail()
        trail_way_ids = list(map(int, trail_way_ids))

        # Set attribute on each edge and node if it's part of the trail
        # trail_nodes is
        trail_nodes = set()
        trail_edges = []
        for u, v, k, way_id in G.edges(keys=True, data='osmid'):
            if way_id not in trail_way_ids:
                continue

            trail_nodes.add(u)
            trail_nodes.add(v)
            trail_edges.append((u, v, k))

        # Add _trail=True for these nodes and edges
        nx.set_node_attributes(
            G, name='_trail', values={k: True
                                      for k in trail_nodes})
        nx.set_edge_attributes(
            G,
            name='_trail',
            values={(u, v, k): True
                    for u, v, k in trail_edges})

        return G

    def _get_osm_way_ids_for_trail(self, alternates=False):
        """Get OSM way ids for trail

        Args:
            - alternates: whether to include alternates. If True, includes only
              alternates, if False, does not include alternates, if None,
              includes both main trail and alternates.

        Returns:
            List[int]: way ids in trail relation. Not necessarily sorted
        """
        trail_relation_id = constants.TRAIL_OSM_RELATION_XW[self.trail_code]
        return self.osm.get_way_ids_for_relation(
            trail_relation_id, alternates=alternates)
