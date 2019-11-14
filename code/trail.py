import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
from geopandas.tools import sjoin
from shapely.geometry import LineString

import data
import osmnx as ox
from data import Halfmile, NationalElevationDataset, OpenStreetMap, Towns
from geom import buffer


class Trail:
    """
    Combine multiple data sources to create all necessary data for trail.

    Args:
        route:
    """
    def __init__(self):
        """

        Args:
            route_iter: generator that yields general (non-exact) route for trail. The idea is that this non-exact route is used to create a buffer
        """
        super(Trail, self).__init__()
        # self.route = route
        # self.handle_section(route_iter)

    def handle_sections(self):
        hm = Halfmile()
        for (section_name, trk), (_, wpt) in zip(hm.trail_iter(),
                                                 hm.wpt_iter()):
            break
            self.handle_section(section_name, trk, wpt)

    def generate_osm_trail_data_for_section(self, section_name, trk):
        """Generate OSM trail data for section

        This downloads OSM way data for the section, then generates the
        section's LineString, and finds intersecting tracks.


        Rough overview:

        - First get ordered list of way IDs for each section relation of the
          trail.
        - Then for each way, find that edge in osmnx dataset
        - Then get the two nodes for that edge
        - One node you should be able to tell was connected to the last edge
        - For the other node, look in the osmnx nodes dataset
        - You should be able to see all the edges that connect to that node. One
          edge is current edge, another should be in the list of ways for the
          relation. Any other edges should be intersections with non PCT data

        Args:
            section_name: name of section, i.e. 'CA_A' or 'OR_C'. This is used to get the OSM way id's that represent that section.
            trk: _Rough_ route line to generate bounding polygon for OSM export. Generally for now this should be a Halfmile section.

        Returns:
            - pct_nodes_sorted: GeoDataFrame with OSMNX nodes that make up the
              trail, in sorted order for that section (from south to north)
            - pct_edges: GeoDataFrame with ordered OSMNX edges that make up the
              PCT. Each row also contains metadata about that OSM way.
            - intersect_edges: GeoDataFrame with OSMNX edges of OSM ways that
              cross the PCT (and are not the PCT). Note that these intersections
              can be of any way type, and include paved roads, unpaved roads,
              and other foot trails. Also note that this does not include
              intersections where there is not a level crossing! So interstate
              highway crossings are not included because the trail does not
              cross the road at the same level.
        """
        osm = OpenStreetMap()

        # Download osm ways for this section
        buf = buffer(trk, distance=2, unit='mile').unary_union
        g = osm.get_ways_for_section(polygon=buf, section_name=section_name)
        nodes, edges = ox.graph_to_gdfs(g)

        # Get ordered list of way ids for this section
        way_ids = osm.get_way_ids_for_section(section_name=section_name)
        first_node = osm.get_nodes_for_way(way_id=way_ids[0])[0]
        last_node = osm.get_nodes_for_way(way_id=way_ids[-1])[-1]

        # Construct ordered list of osmnx edge id's
        # Note that osmnx edge id's are not the same as OSM way id's, because
        # sometimes an OSM way is split in the middle, creating two OSMNX edges
        # despite being a single OSM way
        pct_nodes = [first_node]
        pct_edges = []
        intersect_edges = []

        while True:
            # Keep edges that start from the last node
            _edges = edges[(edges['u'] == pct_nodes[-1])]

            # Check osm list edges
            # Sometimes in the edges DataFrame, the 'osmid' column will be a
            # _list_ value, when there are two osm ids that were simplified into
            # a single edge
            _edges_list_osm = _edges[[
                isinstance(value, list) for value in _edges['osmid']
            ]]
            if len(_edges_list_osm) > 0:
                msg = 'an edge with multiple osm ids is on the PCT'
                assert not any(x in way_ids
                               for x in _edges_list_osm['osmid']), msg

            _edges = _edges[[
                not isinstance(value, list) for value in _edges['osmid']
            ]]

            # Add non-pct edges to list of edge intersections
            # NOTE that this is after taking out rows with lists of osm ids
            non_pct_edges = _edges[~_edges['osmid'].isin(way_ids)]
            intersect_edges.append(non_pct_edges)

            # Keep edges that are in the PCT relation
            _edges = _edges[_edges['osmid'].isin(way_ids)]

            # Remove the edge that goes from the last node to two nodes ago
            if len(pct_nodes) >= 2:
                _edges = _edges[_edges['v'] != pct_nodes[-2]]

            assert len(_edges) == 1, '>1 PCT edge connected to last node'
            _edge = _edges.iloc[0]
            pct_edges.append(_edge)
            pct_nodes.append(_edge['v'])

            if _edge['v'] == last_node:
                break

        # A simple:
        # `nodes[nodes.index.isin(pct_nodes)]`
        # unsorts pct_nodes, so instead, I generate the ordering of nodes, then
        # join them and sort on the order
        node_ordering = [(ind, x) for ind, x in enumerate(pct_nodes)]
        node_ordering = pd.DataFrame(node_ordering, columns=['node_order', 'node_id']).set_index('node_id')

        pct_nodes_unsorted = nodes[nodes.index.isin(pct_nodes)]
        pct_nodes_sorted = pct_nodes_unsorted.join(node_ordering).sort_values('node_order')

        pct_edges = pd.DataFrame(pct_edges)
        pct_edges = gpd.GeoDataFrame(pct_edges)
        intersect_edges = pd.concat(intersect_edges, axis=0)

        return pct_nodes_sorted, pct_edges, intersect_edges


    def add_elevations_to_route(self):
        new_geoms = []
        for row in self.route.itertuples():
            # Get coordinates for line
            g = self._get_elevations_for_linestring(row.geometry)
            new_geoms.append(g)

    def _get_elevations_for_linestring(self, line):
        dem = NationalElevationDataset()

        # NOTE: temporary; remove when all elevation data files are
        # downloaded and unzipped
        coords = [
            coord for coord in line.coords
            if -117 <= coord[0] <= -116 and 32 <= coord[1] <= 33
        ]

        elevs = []
        for coord in coords:
            elevs.append(
                dem.query(lon=coord[0],
                          lat=coord[1],
                          num_buffer=2,
                          interp_kind='cubic'))

        all_coords_z = [(x[0][0], x[0][1], x[1]) for x in zip(coords, elevs)]
        return LineString(all_coords_z)


class PacificCrestTrail(Trail):
    """Construct PCT dataset
    """
    def __init__(self):
        super(PacificCrestTrail, self).__init__()

        self.route = self.construct_route()
        self.intersect_hydrography(self.route)

    def convex_hull(self, overwrite=False):
        """Create localized convex hull with trail buffer and towns
        """
        # Check if already created
        path = data.DataSource().data_dir
        path /= 'pct' / 'polygon' / 'convex_hull_buffer2.geojson'
        if path.exists():
            return gpd.read_file(path)

        # Load all towns
        town_gdf = Towns().boundaries()
        section_polygons = []
        for section, hm_gdf in Halfmile().trail_iter():
            # Get town boundaries in section
            nearby_towns = town_gdf[town_gdf['section'] == section]

            # Get buffer around trail
            hm_buffer = gpd.GeoDataFrame(
                geometry=buffer(hm_gdf, distance=2, unit='mile'))

            # Combine trail buffer and towns
            towns_and_trails = pd.concat([hm_buffer, nearby_towns], sort=False)
            section_polygons.append(towns_and_trails.unary_union.convex_hull)

        section_polygons = gpd.GeoDataFrame(geometry=section_polygons)
        section_polygons.to_file(path, driver='GeoJSON')
        return section_polygons

    def construct_route(self):
        """Construct PCT mainline and alternate routes

        For now, I just use Halfmile's track. However, for the future, I
        envision using the OSM track because then it's easy to generate trail
        junction waypoints using other OSM data. But then I'll need to join
        elevation data from either USGS data or from the Halfmile track.

        TODO: Analytically check how far apart the Halfmile and OSM tracks are.
        Note, you can just use the linestrings to create a polygon and then call
        polygon.area using shapely. Ref: https://stackoverflow.com/q/25439243
        """
        return data.Halfmile().trail()
