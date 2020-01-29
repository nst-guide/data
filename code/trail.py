from typing import Union

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from geopandas.tools import sjoin
from keplergl_quickvis import Visualize as Vis
from shapely.geometry import (
    GeometryCollection, LineString, MultiLineString, Point, Polygon)
from shapely.ops import linemerge, nearest_points, polygonize

import data_source
import geom
import osmnx as ox
from constants import TRAIL_HM_XW, VALID_TRAIL_CODES, VALID_TRAIL_SECTIONS
from data_source import (
    Halfmile, NationalElevationDataset, OpenStreetMap, Towns)
from geom import buffer, reproject, to_2d


class Trail:
    """
    Combine multiple data sources to create all necessary data for trail.

    Args:
        route:
    """
    def __init__(self, trail_code='pct'):
        """

        Args:
            route_iter: generator that yields general (non-exact) route for
            trail. The idea is that this non-exact route is used to create a
            buffer
        """
        super(Trail, self).__init__()

        if trail_code not in VALID_TRAIL_CODES:
            msg = f'Invalid trail_code. Valid values are: {VALID_TRAIL_CODES}'
            raise ValueError(msg)

        self.trail_code = trail_code

        self.osm = OpenStreetMap()
        self.hm = Halfmile()

    def national_parks(self):
        """Generate information for each National Park

        - mile length inside park
        - linestrings inside park

        Returns:
            GeoDataFrame
        """

        # df keys to url keys
        nps_url_xw = {
            'sequ': 'seki',
            'kica': 'seki',
            'lach': 'noca',
        }

        # Get trail track as a single geometric line
        trail = self.hm.trail_full(alternates=False)
        merged = linemerge([*trail.geometry])
        projected = reproject(merged, geom.WGS84, geom.CA_ALBERS)

        # Get NPS boundaries
        nps_bounds = data_source.NationalParkBoundaries().polygon()

        # Reproject to EPSG 3488 for calculations in meters
        nps_bounds = nps_bounds.to_crs(epsg=3488)
        nps_bounds['UNIT_CODE'] = nps_bounds['UNIT_CODE'].str.lower()

        # Find portions of the trail that intersect with these boundaries
        park_trail_intersections = intersect_trail_with_polygons(
            projected, nps_bounds, 'UNIT_CODE')

        # Coerce to GeoDataFrame
        park_trail_intersections = gpd.GeoDataFrame.from_dict(
            park_trail_intersections, orient='index')
        park_trail_intersections.crs = {'init': 'epsg:3488'}

        # Apply xw to index
        idx = park_trail_intersections.index
        park_trail_intersections['parkCode'] = list(
            map(lambda x: nps_url_xw.get(x, x), idx))

        # Search NPS names in wikipedia
        wiki = data_source.Wikipedia()
        wikipedia_urls = []
        for unit_name in nps_bounds['UNIT_NAME']:
            page = wiki.find_page_by_name(unit_name)
            wikipedia_urls.append(page.url)

        nps_bounds['wiki_url'] = wikipedia_urls

        # Some unit codes in the data are non-standard, e.g. modern codes should
        # work with `https://nps.gov/${unit_code}`
        nps_bounds['url_code'] = nps_bounds['UNIT_CODE'].apply(
            lambda code: nps_url_xw.get(code, code))
        nps_bounds['nps_url'] = nps_bounds['url_code'].apply(
            lambda code: f'https://www.nps.gov/{code.lower()}')

        # Make sure that all these pages exist
        redirected_urls = []
        for url in nps_bounds['nps_url']:
            r = requests.head(url, allow_redirects=True)
            if r.status_code == 404:
                raise ValueError(f'NPS 404 for: {url}')

            redirected_urls.append(r.url)

        # Set the nps_url to the redirected url. Generally this just appends
        # `index.htm` to the previous url
        nps_bounds['nps_url'] = redirected_urls

        # Get blurb about each park from NPS API
        nps_api = data_source.NationalParksAPI()
        park_codes = list(nps_bounds['url_code'].unique())
        r = nps_api.query(park_codes=park_codes, endpoint='parks')

        # Coerce JSON response to DataFrame
        nps_api_dfs = []
        for park_code, res in r.items():
            df = pd.DataFrame.from_records(res)
            nps_api_dfs.append(df)

        nps_api_df = pd.concat(nps_api_dfs)

        # Merge trail geometry data with NPS API data
        gdf = pd.merge(park_trail_intersections, nps_api_df, on='parkCode')
        # Remove geometry column, which will be overwritten by nat parks
        # polygons in next merge
        gdf = gdf.drop('geometry', axis=1)

        # Merge on wikipedia url
        gdf = pd.merge(
            gdf,
            nps_bounds[['geometry', 'wiki_url', 'url_code']],
            how='right',
            left_on='parkCode',
            right_on='url_code')

        # Reproject back to EPSG 4326
        gdf = gdf.to_crs(epsg=4326)

        return gdf

    def wildernesses(self):
        """Generate information for wilderness areas
        """
        # Get trail track as a single geometric line
        trail = self.hm.trail_full(alternates=False)
        merged = linemerge([*trail.geometry])
        projected = reproject(merged, geom.WGS84, geom.CA_ALBERS)

        # Get Wilderness boundaries
        wild_bounds = data_source.WildernessBoundaries().polygon()
        # Reproject to EPSG 3488
        wild_bounds = wild_bounds.to_crs(epsg=3488)

        # Find portions of the trail that intersect with these boundaries
        intersection = intersect_trail_with_polygons(
            projected, wild_bounds, 'WID')

        # Coerce to GeoDataFrame
        gdf = gpd.GeoDataFrame.from_dict(intersection, orient='index')
        gdf.crs = {'init': 'epsg:3488'}

        # The Description column doesn't contain the full description for the
        # park from Wilderness.net, so scrape Wilderness.net
        scraper = data_source.WildernessConnectScraper()
        all_regs = []
        all_descs = []
        for url in wild_bounds['URL']:
            # Note, you need to navigate away or manually reload between the
            # regulations and description pages, or else Chromedriver will
            # stall. I think this is because the pages on the website are all
            # HTML fragments, i.e. `#general`, and not actually pages.
            #
            # I actually still find that sometimes it gets stuck. If it seems
            # like it's taking a while, try clicking "Management & Regulation"
            # in the Chromedriver window, and that might fix it
            regs = scraper.get_regulations(url)
            desc = scraper.get_description(url)

            all_regs.append(regs)
            all_descs.append(desc)

        # return d

    def national_forests(self):
        # Get trail track as a single geometric line
        trail = self.hm.trail_full(alternates=False)
        merged = linemerge([*trail.geometry])
        projected = reproject(merged, geom.WGS84, geom.CA_ALBERS)

        # Get Wilderness boundaries
        fs_bounds = data_source.NationalForestBoundaries().polygon()
        # Reproject to EPSG 3488
        fs_bounds = fs_bounds.to_crs(epsg=3488)

        # Find portions of the trail that intersect with these boundaries
        d = intersect_trail_with_polygons(projected, fs_bounds, 'FORESTORGC')

        # Ping RIDB searching by Forest Name
        # NOTE: if you end up splitting National Forest MultiPolygons into
        # multiple rows of single Polygons, you might want to deduplicate before
        # pinging the API
        ridb_api = data_source.RecreationGov()
        results = []
        for forest_name in fs_bounds['FORESTNAME']:
            # Sometimes the response with matching name is >5 deep
            d = ridb_api.query(
                query=forest_name, endpoint='recareas', limit=10, full=False)

            # If any result has the same RecAreaName, choose that. Otherwise,
            # choose the first one.
            append_index = None
            for i in range(len(d['RECDATA'])):
                if d['RECDATA'][i]['RecAreaName'].lower() == forest_name.lower(
                ):
                    append_index = i

            if append_index is not None:
                results.append(d['RECDATA'][append_index])
            else:
                results.append({})

        [(name, x.get('RecAreaName'), x.get('RecAreaID'))
         for x, name in zip(results, fs_bounds['FORESTNAME'])]
        return d

    def wikipedia_articles(
            self, buffer_dist=2, buffer_unit='mile', attrs=['title', 'url']):
        """Get wikipedia articles for trail

        Args:

        - buffer_dist: numerical distance for buffer around trail
        - buffer_unit: units for buffer_dist, can be 'mile', 'meter', 'kilometer'
        - attrs: list of wikipedia page attributes to keep. Geometry is always
          kept. Options are:

            - categories: List of categories of a page. I.e. names of subsections within article
            - content: Plain text content of the page, excluding images, tables, and other data.
            - html: Get full page HTML. Warning: this can be slow for large
              pages.
            - images: List of URLs of images on the page.
            - links: List of titles of Wikipedia page links on a page.
            - original_title:
            - pageid:
            - parent_id: Revision ID of the parent version of the current revision of this page. See revision_id for more information.
            - references: List of URLs of external links on a page. May include external links within page that aren’t technically cited anywhere.
            - revision_id: Revision ID of the page.

              The revision ID is a number that uniquely identifies the current
              version of the page. It can be used to create the permalink or for
              other direct API calls. See Help:Page history for more
              information.
            - sections: List of section titles from the table of contents on the page.
            - summary: Plain text summary of the page.
            - title: Title of the page
            - url: URL of the page
        """
        # Make sure desired attributes are valid
        valid_attrs = [
            'categories', 'content', 'html', 'images', 'links',
            'original_title', 'pageid', 'parent_id', 'references',
            'revision_id', 'sections', 'summary', 'title', 'url'
        ]
        assert (all(attr) in valid_attrs for attr in attrs), 'Invalid attrs'

        # Get trail track as a single geometric line
        trail = self.hm.trail_full(alternates=False)
        buf = geom.buffer(
            trail, distance=buffer_dist, unit=buffer_unit).unary_union
        wiki = data_source.Wikipedia()
        pages = wiki.find_pages_for_polygon(buf)

        data = []
        for page in pages:
            d = {}
            for attr in attrs:
                d[attr] = getattr(page, attr)

            # Page coordinates are in lat, lon order
            d['geometry'] = Point(page.coordinates[::-1])

            data.append(d)

        gdf = gpd.GeoDataFrame(data, crs={'init': 'epsg:4326'})
        return gdf


    def track(self, trail_section=None, alternates=False):
        """Load LineStrings of trail as GeoDataFrame
        """
        if trail_section is None:
            gdf = self.hm.trail_full(alternates=alternates)
        else:
            msg = 'Invalid trail_section'
            assert trail_section in VALID_TRAIL_SECTIONS[self.trail_code], msg
            hm_sections = TRAIL_HM_XW[trail_section]
            gdf = self.hm.trail_section(
                section_names=hm_sections, alternates=alternates)

        return gdf

    def towns(self, trail_section=None):
        """Load polygons of towns as GeoDataFrame
        """
        msg = f'Invalid trail_section. Valid values are: {VALID_TRAIL_SECTIONS}'
        if trail_section is not None:
            assert trail_section in VALID_TRAIL_SECTIONS[self.trail_code], msg

        gdf = Towns().boundaries()
        if trail_section is not None:
            hm_sections = TRAIL_HM_XW[trail_section]
            gdf = gdf[gdf['section'].str.lower().isin(hm_sections)]

        return gdf

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
        3. Parse OSM trail data
        4. Using the trail buffer and trail line, find nearby water sources from
          NHD dataset.

        Args:
            wpt: Halfmile waypoints for given section of trail
            use_cache: Whether to use existing extracts
        """
        # Check cache
        data_dir = data_source.find_data_dir()
        raw_dir = data_dir / 'raw' / 'osm' / 'clean'
        raw_dir.mkdir(parents=True, exist_ok=True)
        paths = [
            raw_dir / f'{self.section_name}_nodes.geojson',
            raw_dir / f'{self.section_name}_edges.geojson',
            raw_dir / f'{self.section_name}_intersections.geojson'
        ]

        # 1. Generate OSM trail data
        if self.use_cache and all(path.exists() for path in paths):
            res = [gpd.read_file(path) for path in paths]
        else:
            res = self.generate_osm_trail_data()
            for gdf, path in zip(res, paths):
                gdf.to_file(path, driver='GeoJSON')

        nodes, edges, intersections = res

        # 2. Get centerline of trail from OSM data
        trail_line = self.construct_linestring_from_edges(edges)

        # 3. Parse OSM trail data
        self.parse_generated_osm_trail_data(nodes, edges, intersections)

        # 4. Intersect with NHD data
        self.intersect_hydrography(trail_line=trail_line)

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
        g = osm.get_ways_for_polygon(
            polygon=self.buffer,
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
                assert not any(
                    x in way_ids for x in _edges_list_osm['osmid']), msg

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
        node_ordering = pd.DataFrame(
            node_ordering, columns=['node_order',
                                    'node_id']).set_index('node_id')

        pct_nodes_unsorted = nodes[nodes.index.isin(pct_nodes)]
        pct_nodes_sorted = pct_nodes_unsorted.join(node_ordering).sort_values(
            'node_order')

        pct_edges = pd.DataFrame(pct_edges)
        pct_edges = gpd.GeoDataFrame(pct_edges)
        intersect_edges = pd.concat(intersect_edges, axis=0)

        return pct_nodes_sorted, pct_edges, intersect_edges

    def construct_linestring_from_edges(
            self, edges: gpd.GeoDataFrame) -> LineString:
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

    def compute_deviance_of_two_lines(
            self, line1: LineString, line2: LineString) -> float:
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

    def intersect_hydrography(self, trail_line):
        # TODO: pass the trail + alternates
        # TODO pass full OSM path network near trail (take out railways), so
        # that I can find springs or other water sources that are off trail but
        # there's a trail to them, + calculate distance
        trail = gpd.GeoDataFrame([], geometry=[trail_line])
        buffer = gpd.GeoDataFrame([], geometry=[self.buffer])

        hydro = USGSHydrography()
        files = hydro.nhd_files_for_geometry(trail_line)

    def _hydro_line(self, hydro, files, trail, buffer):
        INTERMITTENT = 46003
        PERENNIAL = 46006
        flowline = hydro.read_files(files=files, layer='NHDFlowline')
        flowline = flowline[flowline['FCode'].isin([INTERMITTENT, PERENNIAL])]
        flowline = sjoin(flowline, trail, how='inner')

        # Intersect flowlines and trail to get points
        flow_cols = flowline.columns
        trail_cols = trail.columns
        msg = 'Flowline and trail column names must be distinct'
        assert all(x not in flow_cols for x in trail_cols), msg

        data = []
        for flow in flowline.itertuples(index=False):
            for tr in trail.itertuples(index=False):
                intersect = flow.geometry.intersection(tr.geometry)

                # Apparently, when two lines don't cross, the result is a
                # GeometryCollection with `.geoms == []`
                if isinstance(intersect,
                              GeometryCollection) and (intersect.geoms == []):
                    continue

                # Generate row as the attributes of each gdf, then separately
                # add geometry as the intersection point
                row = [
                    v for k, v in zip(flow_cols, flow)
                    if k != flowline.geometry.name
                ]
                row.extend([
                    v for k, v in zip(trail_cols, trail)
                    if k != trail.geometry.name
                ])
                row.append(intersect)
                data.append(row)

        cols = [
            *[x for x in flow_cols if x != 'geometry'],
            *[x for x in trail_cols if x != 'geometry'], 'geometry'
        ]
        gdf = gpd.GeoDataFrame(data, columns=cols)

        gdf['perennial'] = gdf['FCode'] == PERENNIAL
        gdf = gdf[['GNIS_Name', 'perennial', 'geometry']]
        gdf = gdf.rename(columns={'GNIS_Name': 'name'})
        return gdf.to_dict('records')

    def add_elevations_to_route(self):
        new_geoms = []
        for row in self.route.itertuples():
            # Get coordinates for line
            g = self._get_elevations_for_linestring(row.geometry)
            new_geoms.append(g)

    def _get_elevations_for_linestring(self, line, interp_kind):
        dem = NationalElevationDataset()

        coords = line.coords
        elevs = dem.query(coords)
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


def intersect_trail_with_polygons(
        trail: LineString, gdf: gpd.GeoDataFrame, key_col: str):
    """Intersect trail with polygons to produce overlapping line segments

    Both trail and gdf must be projected to a projected coordinate system
    before being passed to this function.

    This is used, e.g. to find the portions of the trail that are within
    national parks or national forests.

    Args:
        - trail: projected LineString of trail
        - gdf: projected GDF of polygons to find intersections of. It shouldn't matter if an area shows up once as a MultiPolygon or multiple times (with the same `key_col` value) as individual Polygons.
        - key_col: column of GDF to use as keys of dict

    Returns:
        - {key_col: {'geometry': MutliLineString, 'length': float}}
        where `lines` is a list of lines where the trail intersects with the
        given polygon, and `length` is the sum of distances in the polygon.
    """
    intersections = {}
    # Iterate over GeoDataFrame
    for row in gdf.itertuples():
        # Compute intersection
        int_line = trail.intersection(row.geometry)

        # Get key_col in dataset
        key = getattr(row, key_col)

        # Instantiate dict with key
        intersections[key] = intersections.get(key, {})

        if int_line.type == 'LineString':
            intersections[key]['geometry'] = MultiLineString([int_line])
        elif int_line.type == 'MultiLineString':
            intersections[key]['geometry'] = int_line
        else:
            msg = 'intersection of Polygon, LineString should be LineString'
            raise ValueError(msg)

    # Add length in projected coordinates to dictionary
    for key, d in intersections.items():
        intersections[key]['length'] = d['geometry'].length

    return intersections


def approx_trail(
        trail_code: str, trail_section: Union[str, bool], alternates: bool):
    """Retrieve approximate trail geometry

    There are many instances when I need an _approximate_ trail geometry. First
    and foremost, I use the approximate trail line to generate the polygons
    within which to download OSM data! It takes _forever_ to download the entire
    PCT relation through the OSM api, because you have to recursively download
    relations -> way -> nodes, and so make tens of thousands of http requests.

    (This function isn't currently used for downloading OSM; that's hardcoded,
    but it can be refactored in the future.)

    Otherwise, also helpful for:

    - getting wikipedia articles near the trail
    - transit near the trail

    Args:
        - trail_code: the code for the trail of interest, i.e. 'pct'
        - trail_section: the code for the trail section of interest, i.e.
          ca_south. If True, returns the entire trail.
        - alternates: if True, includes alternates

    Returns:
        GeoDataFrame representing trail
    """
    if trail_code not in VALID_TRAIL_CODES:
        msg = f'Invalid trail_code. Valid values are: {VALID_TRAIL_CODES}'
        raise ValueError(msg)

    if trail_section != True:
        if trail_section not in VALID_TRAIL_SECTIONS.get(trail_code):
            msg = f'Invalid trail_section. Valid values are: {VALID_TRAIL_SECTIONS}'
            raise ValueError(msg)

    if trail_code == 'pct':
        hm = Halfmile()
        if trail_section == True:
            return hm.trail_full(alternates=alternates)

        hm_sections = TRAIL_HM_XW.get(trail_section)
        return hm.trail_section(hm_sections, alternates=alternates)


def milemarker_for_points(points, trail_code='pct'):
    """Find mile marker for point

    Args:
        point: list of shapely point in EPSG 4326
        trail_code: which trail
    """
    if trail_code != 'pct':
        raise ValueError('invalid trail_code')

    # For now, since I don't have the original Halfmile data with full accuracy,
    # I take the two nearest half-mile waypoints and interpolate between them.
    hm = Halfmile()
    # Load waypoints into GeoDataFrame
    gdf = hm.wpt_full()

    # Select only mile marker waypoints
    gdf = gdf[gdf['symbol'] == 'Triangle, Red']

    # Some mile marker waypoints exist in multiple sections; deduplicate on name
    gdf = gdf.drop_duplicates('name')

    # Coerce the name to a decimal number
    gdf['mi'] = pd.to_numeric(gdf['name'].str.replace('-', '.'))

    wpts_geom = gdf.geometry.unary_union
    mile_markers = []
    for point in points:
        # Find the nearest point in waypoint dataset
        nearest = to_2d(gdf).geometry == nearest_points(point, wpts_geom)[1]
        assert nearest.sum() == 1, 'Should be one nearest point'

        # Find row that belongs to
        # (matching is based on the geometry)
        row = gdf[nearest]

        # Get mile marker of that row
        mm = row['mi'].values[0]
        mile_markers.append(mm)

    return mile_markers
