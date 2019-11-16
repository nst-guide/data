import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
from geopandas.tools import sjoin
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize

import data as Data
import geom
import osmnx as ox
from data import Halfmile, NationalElevationDataset, OpenStreetMap, Towns
from geom import buffer, reproject


class Trail:
    """
    Combine multiple data sources to create all necessary data for trail.

    Args:
        route:
    """
    def __init__(self):
        """

        Args:
            route_iter: generator that yields general (non-exact) route for
            trail. The idea is that this non-exact route is used to create a
            buffer
        """
        super(Trail, self).__init__()
        self.osm = OpenStreetMap()
        self.hm = Halfmile()

    def handle_sections(self, use_cache: bool = True):
        hm = Halfmile()
        for (section_name, trk), (_, wpt) in zip(hm.trail_iter(),
                                                 hm.wpt_iter()):
            buf = buffer(trk, distance=2, unit='mile').unary_union
            self.handle_section(section_name=section_name,
                                polygon=buf,
                                wpt=wpt,
                                use_cache=use_cache)

            self.handle_section(wpt=wpt, use_cache=use_cache)


class TrailSection:
    """docstring for TrailSection"""
    def __init__(self, buffer, section_name, use_cache):
        """

        Args:
            buffer: buffer or bbox around trail, used to filter OSM data
            section_name: Name of section, i.e. 'CA_A' or 'OR_C'
            use_cache: Whether to use existing extracts
        """
        super(TrailSection, self).__init__()
        self.buffer = buffer
        self.section_name = section_name
        self.use_cache = use_cache

    def main(self, wpt):
        """Do everything for a given section of trail

        1. Download ways of type "highway" and "railway" for a buffer around the
          trail. Using this graph, find the edges and nodes that make up the
          PCT, and all roads, trails, and railways that intersect the PCT.
        2. Using the edges that make up the PCT, create the PCT line
        3. Using the trail buffer and trail line, find nearby water sources from
          NHD dataset.

        Args:
            wpt: Halfmile waypoints for given section of trail
            use_cache: Whether to use existing extracts
        """
        # Check cache
        data_dir = Data.find_data_dir()
        raw_dir = data_dir / 'raw' / 'osm' / 'clean'
        raw_dir.mkdir(parents=True, exist_ok=True)
        paths = [
            raw_dir / f'{section_name}_nodes.geojson',
            raw_dir / f'{section_name}_edges.geojson',
            raw_dir / f'{section_name}_intersections.geojson'
        ]

        if use_cache and all(path.exists() for path in paths):
            res = [gpd.read_file(path) for path in paths]
        else:
            # Generate OSM data
            res = self.generate_osm_trail_data()
            for gdf, path in zip(res, paths):
                gdf.to_file(path, driver='GeoJSON')

        nodes, edges, intersections = res

        # Get linestring from edges
        trail_line = self.construct_linestring_from_edges(edges)

        # Parse OSM data
        self.parse_generated_osm_trail_data(nodes, edges, intersections)


    def generate_osm_trail_data(
            self) -> (gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame):
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
        g = osm.get_ways_for_polygon(polygon=self.buffer,
                                     section_name=self.section_name,
                                     overwrite=(not self.use_cache))
        nodes, edges = ox.graph_to_gdfs(g)

        # Get ordered list of way ids for this section
        way_ids = osm.get_way_ids_for_section(section_name=self.section_name)
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

            # Keep edges that are in the PCT relation
            _edges = _edges[_edges['osmid'].isin(way_ids)]

            # Remove the edge that goes from the last node to two nodes ago
            if len(pct_nodes) >= 2:
                _edges = _edges[_edges['v'] != pct_nodes[-2]]

            assert len(_edges) == 1, '>1 PCT edge connected to last node'
            _edge = _edges.iloc[0]
            pct_edges.append(_edge)
            pct_nodes.append(_edge['v'])
            intersect_edges.append(non_pct_edges)

            if _edge['v'] == last_node:
                break

        # A simple:
        # `nodes[nodes.index.isin(pct_nodes)]`
        # unsorts pct_nodes, so instead, I generate the ordering of nodes, then
        # join them and sort on the order
        node_ordering = [(ind, x) for ind, x in enumerate(pct_nodes)]
        node_ordering = pd.DataFrame(node_ordering,
                                     columns=['node_order',
                                              'node_id']).set_index('node_id')

        pct_nodes_unsorted = nodes[nodes.index.isin(pct_nodes)]
        pct_nodes_sorted = pct_nodes_unsorted.join(node_ordering).sort_values(
            'node_order')

        pct_edges = pd.DataFrame(pct_edges)
        pct_edges = gpd.GeoDataFrame(pct_edges)
        intersect_edges = pd.concat(intersect_edges, axis=0)

        return pct_nodes_sorted, pct_edges, intersect_edges

    def construct_linestring_from_edges(self,
                                        edges: gpd.GeoDataFrame) -> LineString:
        """Given OSM edges that make up a section, return its LineString

        Args:
            - edges: GeoDataFrame of edges to form into a line

        Returns:
            LineString of connected edges
        """
        line = linemerge(edges.geometry.values)

        # Make sure it's sorted in the correct direction
        same_order = line.coords[0] == edges.iloc[0].geometry.coords[0]
        if same_order:
            return line

        raise NotImplementedError('Linestring not in correct direction')

    def compute_deviance_of_two_lines(self, line1: LineString,
                                      line2: LineString) -> float:
        """Compute the deviance of two lines

        It's important to check how accurate the OSM track is compared to other
        tracks. So here I use two provided lines to create the polygons that
        make up the deviations between the two lines, then I add those areas
        together, and divide by the length of each line. Note that the two lines
        do need to be sorted in the same direction.

        References:

        Look at the edit of the Q here: https://stackoverflow.com/q/25439243.
        And for splitting the polygon into non-overlapping polygons:
        https://gis.stackexchange.com/a/243498

        Args:
            - line1: first line
            - line2: second line

        Returns:
            - A float for the average distance in meters between the two lines
        """
        # Reproject lines to California Albers
        line1 = reproject(line1, geom.WGS84, geom.CA_ALBERS)
        line2 = reproject(line2, geom.WGS84, geom.CA_ALBERS)

        # Check that lines are in the same direction
        # Get distance between start point of each line, then assert they're
        # within 100m
        start_dists = Point(line1.coords[0]).distance(Point(line2.coords[0]))
        msg = 'Beginning of two lines not within 1000m'
        assert start_dists <= 1000, msg

        # Make a loop with line1, line2 reversed, and the first point of line1
        polygon_coords = [*line1.coords, *line2.coords[::-1], line1.coords[0]]

        # Make sure all coords only have two dimensions
        polygon_coords = [(x[0], x[1]) for x in polygon_coords]

        # Make polygon
        poly = Polygon(polygon_coords)

        # If I just take the area now, the "positive" and "negative" parts will
        # cancel out. I.e. consider a bowtie polygon:
        # Polygon([(0,0),(0,1),(1,0),(1,1),(0,0)])
        # The area of that is zero because the halves cancel out.
        # To fix that, I'm going to take the exterior of the polygon, intersect
        # it with itself, and then form new polygons, following this answer:
        # https://gis.stackexchange.com/a/243498
        exterior = poly.exterior
        multils = exterior.intersection(exterior)
        polygons = polygonize(multils)
        areas = [p.area for p in polygons]
        area = sum(areas)

        # Line dist
        dist = (line1.length + line2.length) / 2

        # Average deviance per meter (also a percent)
        deviance = area / dist

        return deviance


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


    def _create_route_no_elevation(self):
        """Create route from OSM data using API

        Using the OSM.org API is so so slow because it has to make so many
        individual requests. This function is kept for now, but it's so slow
        that it may be deleted in the future.
        """

        pct_relation_id = self.osm.trail_ids['pct']
        section_relations = self.osm.get_relations_within_pct(pct_relation_id)

        full_data = []

        for section_name, relation_id in section_relations.items():
            way_ids = self.osm.get_way_ids_for_relation(relation_id)
            all_points_in_section = []
            for way_id in way_ids:
                nodes = self.osm.get_nodes_for_way(way_id)
                node_infos = [self.osm.get_node_info(n) for n in nodes]
                all_points_in_section.extend([
                    Point(float(n['lon']), float(n['lat'])) for n in node_infos
                ])

            section_line = LineString(all_points_in_section)
            full_data.append(section_line)



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
