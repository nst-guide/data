from math import isnan
from typing import List, Union

import geojson
import geopandas as gpd
import pandas as pd
import requests
from geopandas.tools import sjoin
from keplergl_quickvis import Visualize as Vis
from shapely.geometry import (
    GeometryCollection, LineString, MultiLineString, Point, Polygon)
from shapely.ops import linemerge, nearest_points, polygonize

import constants
import data_source
import geom
import osmnx as ox
from constants import VALID_TRAIL_CODES, VALID_TRAIL_SECTIONS
from constants.pct import TRAIL_HM_XW
from data_source import (
    Halfmile, NationalElevationDataset, OpenStreetMap, Towns)
from geom import reproject, to_2d


class Trail:
    """Combine multiple data sources to create all necessary data for trail.
    """
    def __init__(self, trail_code='pct'):
        """
        Args:
            - trail_code: code for trail of interest, e.g. `pct`
        """
        super(Trail, self).__init__()

        if trail_code not in VALID_TRAIL_CODES:
            msg = f'Invalid trail_code. Valid values are: {VALID_TRAIL_CODES}'
            raise ValueError(msg)

        self.trail_code = trail_code
        self.crs = constants.TRAIL_EPSG_XW[trail_code]

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
        projected = reproject(merged, geom.WGS84, self.crs)

        # Get NPS boundaries
        nps_bounds = data_source.NationalParkBoundaries().polygon()

        # Reproject to projected coordinate system for calculations in meters
        nps_bounds = nps_bounds.to_crs(epsg=self.crs)
        nps_bounds['UNIT_CODE'] = nps_bounds['UNIT_CODE'].str.lower()

        # Find portions of the trail that intersect with these boundaries
        park_trail_intersections = intersect_trail_with_polygons(
            projected, nps_bounds, 'UNIT_CODE')

        # Coerce to GeoDataFrame
        park_trail_intersections = gpd.GeoDataFrame.from_dict(
            park_trail_intersections, orient='index')
        park_trail_intersections.crs = {'init': f'epsg:{self.crs}'}

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
        projected = reproject(merged, geom.WGS84, self.crs)

        # Get Wilderness boundaries
        wild_bounds = data_source.WildernessBoundaries().polygon()
        # Reproject to projected coordinate system in meters
        wild_bounds = wild_bounds.to_crs(epsg=self.crs)

        # Find portions of the trail that intersect with these boundaries
        intersection_dict = intersect_trail_with_polygons(
            projected, wild_bounds, 'WID')

        # Merge this back onto fs_bounds
        # Here I discard the linestring intersection of where the trail is
        # inside the polygons
        intersection_df = pd.DataFrame(
            gpd.GeoDataFrame.from_dict(intersection_dict,
                                       orient='index')['length'])
        wild_bounds = pd.merge(
            wild_bounds,
            intersection_df,
            how='left',
            left_on='WID',
            right_index=True,
        )

        # Reproject back to epsg 4326
        wild_bounds = wild_bounds.to_crs(epsg=4326)

        # Search names in wikipedia
        wiki = data_source.Wikipedia()
        wiki_pages = []
        for name in wild_bounds['NAME']:
            page = wiki.find_page_by_name(name)
            wiki_pages.append(page)

        assert len(wiki_pages) == len(wild_bounds), 'Incorrect # from API'

        wiki_images = []
        wiki_urls = []
        wiki_summaries = []
        for page in wiki_pages:
            if page is None:
                wiki_images.append(None)
                wiki_urls.append(None)
                wiki_summaries.append(None)
                continue

            wiki_images.append(wiki.best_image_on_page(page))
            wiki_urls.append(page.url)
            wiki_summaries.append(page.summary)

        wild_bounds['wiki_image'] = wiki_images
        wild_bounds['wiki_url'] = wiki_urls
        wild_bounds['wiki_summary'] = wiki_summaries

        # For now I'm not going to try to deal with scraping wilderness.net
        #
        # # The Description column doesn't contain the full description for the
        # # park from Wilderness.net, so scrape Wilderness.net
        # scraper = data_source.WildernessConnectScraper()
        # all_regs = []
        # all_descs = []
        # for url in wild_bounds['URL']:
        #     # Note, you need to navigate away or manually reload between the
        #     # regulations and description pages, or else Chromedriver will
        #     # stall. I think this is because the pages on the website are all
        #     # HTML fragments, i.e. `#general`, and not actually pages.
        #     #
        #     # I actually still find that sometimes it gets stuck. If it seems
        #     # like it's taking a while, try clicking "Management & Regulation"
        #     # in the Chromedriver window, and that might fix it
        #     regs = scraper.get_regulations(url)
        #     desc = scraper.get_description(url)
        #
        #     all_regs.append(regs)
        #     all_descs.append(desc)

        return wild_bounds

    def national_forests(self):
        # Get trail track as a single geometric line
        trail = self.hm.trail_full(alternates=False)
        merged = linemerge([*trail.geometry])
        projected = reproject(merged, geom.WGS84, self.crs)

        # Get Wilderness boundaries
        fs_bounds = data_source.NationalForestBoundaries().polygon()
        # Reproject to projected coordinate system in meters
        fs_bounds = fs_bounds.to_crs(epsg=self.crs)

        # Find portions of the trail that intersect with these boundaries
        intersection_dict = intersect_trail_with_polygons(
            projected, fs_bounds, 'FORESTORGC')

        # Merge this back onto fs_bounds
        # Here I discard the linestring intersection of where the trail is
        # inside the polygons
        intersection_df = pd.DataFrame(
            gpd.GeoDataFrame.from_dict(intersection_dict,
                                       orient='index')['length'])
        fs_bounds = pd.merge(
            fs_bounds,
            intersection_df,
            how='left',
            left_on='FORESTORGC',
            right_index=True,
        )

        # Search names in wikipedia
        wiki = data_source.Wikipedia()
        wikipedia_pages = []
        for name in fs_bounds['FORESTNAME']:
            page = wiki.find_page_by_name(name)
            wikipedia_pages.append(page)

        assert len(wikipedia_pages) == len(fs_bounds), 'Incorrect # from API'

        wiki_images = [
            wiki.best_image_on_page(page) for page in wikipedia_pages
        ]
        wiki_urls = [page.url for page in wikipedia_pages]
        wiki_summaries = [page.summary for page in wikipedia_pages]

        fs_bounds['wiki_image'] = wiki_images
        fs_bounds['wiki_url'] = wiki_urls
        fs_bounds['wiki_summary'] = wiki_summaries

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

        # For each forest that is found, also get the official link and any
        # images
        official_links = []
        for ridb_result in results:
            if ridb_result == {}:
                official_links.append(None)
                continue

            rec_area_id = ridb_result['RecAreaID']
            official_link = ridb_api.official_link(rec_area_id)

            official_links.append(official_link)

        # For visual inspection
        # [(name, x.get('RecAreaName'), x.get('RecAreaID'))
        #  for x, name in zip(results, fs_bounds['FORESTNAME'])]

        # Merge API results
        # They should be in order, so I just add the column
        assert len(official_links) == len(
            fs_bounds), 'Incorrect # of results from API'
        fs_bounds['official_url'] = official_links

        # Reproject back to EPSG 4326
        fs_bounds = fs_bounds.to_crs(epsg=4326)

        return fs_bounds

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
            - best_image: My attempt to get the single best image url.
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
        # is best_image asked for
        best_image = 'best_image' in attrs
        # Make sure it's not left in attrs list
        attrs = [attr for attr in attrs if attr != 'best_image']

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
            if best_image:
                d['best_image'] = wiki.best_image_on_page(page)

            for attr in attrs:
                d[attr] = getattr(page, attr)

            # Page coordinates are in lat, lon order
            d['geometry'] = Point(page.coordinates[::-1])

            data.append(d)

        gdf = gpd.GeoDataFrame(data, crs={'init': 'epsg:4326'})
        return gdf

    def wildfire_historical(self, start_year):
        # Get trail track as a single geometric line
        trail_alt = self.hm.trail_full(alternates=True)
        trail_no_alt = self.hm.trail_full(alternates=False)
        merged = linemerge([*trail_no_alt.geometry])
        projected = reproject(merged, geom.WGS84, self.crs)

        # Get historical wildfire boundaries
        # I use trail_alt for the geometry to keep wildfires that intersect
        # alternates
        bounds = data_source.NIFC().perimeters(
            geometry=trail_alt, start_year=start_year)
        # Reproject to projected coordinate system
        bounds = bounds.to_crs(epsg=self.crs)

        # Find portions of the trail that intersect with these boundaries
        intersection_dict = intersect_trail_with_polygons(
            projected, bounds, 'firecode')

        # Merge this back onto bounds
        # Here I discard the linestring intersection of where the trail is
        # inside the polygons
        intersection_df = pd.DataFrame(
            gpd.GeoDataFrame.from_dict(intersection_dict,
                                       orient='index')['length'])
        bounds = pd.merge(
            bounds,
            intersection_df,
            how='left',
            left_on='firecode',
            right_index=True,
        )

        # Reproject back to epsg 4326
        bounds = bounds.to_crs(epsg=4326)

        # Get titles from predefined crosswalk
        wiki = data_source.Wikipedia()
        wiki_titles = bounds['name'].apply(
            lambda x: constants.FIRE_NAME_WIKIPEDIA_XW.get(x, None))
        wiki_pages = []
        for title in wiki_titles:
            if title is None:
                wiki_pages.append(None)
                continue

            wiki_pages.append(wiki.page(title))

        assert len(wiki_pages) == len(bounds), 'Incorrect # of results'

        wiki_images = []
        wiki_urls = []
        wiki_summaries = []
        for page in wiki_pages:
            if page is None:
                wiki_images.append(None)
                wiki_urls.append(None)
                wiki_summaries.append(None)
                continue

            wiki_images.append(wiki.best_image_on_page(page))
            wiki_urls.append(page.url)
            wiki_summaries.append(page.summary)

        bounds['wiki_image'] = wiki_images
        bounds['wiki_url'] = wiki_urls
        bounds['wiki_summary'] = wiki_summaries

        # Check if inciwebid's actually link to a page that exists
        checked_ids = []
        baseurl = 'https://inciweb.nwcg.gov/incident/'
        for inciwebid in bounds['inciwebid']:
            if not inciwebid:
                checked_ids.append(None)
                continue

            url = baseurl + inciwebid
            r = requests.get(url)
            if r.status_code == 404:
                checked_ids.append(None)
                continue

            checked_ids.append(inciwebid)

        bounds['inciwebid'] = checked_ids
        return bounds

    def transit(
            self,
            trail=True,
            town=True,
            trail_buffer_dist=1000,
            trail_buffer_unit='meter'):
        """Get transit information for trail
        """

        transit = data_source.Transit()

        # Get all stops that intersect trail and town geometries
        all_all_stops = {}
        all_nearby_stops = {}
        all_routes = {}
        if trail:
            for section_name, gdf in self.hm.trail_iter():
                trail_buf = geom.buffer(
                    gdf, distance=trail_buffer_dist,
                    unit=trail_buffer_unit).unary_union

                _nearby_stops, _all_stops, _routes = transit.download(trail_buf)

                # Add each dict to `all_${dict}`, but set the _trail key to True
                for key, val in _nearby_stops.items():
                    all_nearby_stops[key] = all_nearby_stops.get(key, val)
                    all_nearby_stops[key]['_trail'] = True

                for key, val in _all_stops.items():
                    all_all_stops[key] = all_all_stops.get(key, val)
                    all_all_stops[key]['_trail'] = True

                for key, val in _routes.items():
                    all_routes[key] = all_routes.get(key, val)
                    all_routes[key]['_trail'] = True

        if town:
            for polygon in self.towns().geometry:
                _nearby_stops, _all_stops, _routes = transit.download(polygon)

                # Add each dict to `all_${dict}`, but set the _trail key to True
                for key, val in _nearby_stops.items():
                    all_nearby_stops[key] = all_nearby_stops.get(key, val)
                    all_nearby_stops[key]['_town'] = True

                for key, val in _all_stops.items():
                    all_all_stops[key] = all_all_stops.get(key, val)
                    all_all_stops[key]['_town'] = True

                for key, val in _routes.items():
                    all_routes[key] = all_routes.get(key, val)
                    all_routes[key]['_town'] = True

        # Combine all_all_stops and all_nearby_stops into single dict
        stops = {}
        for key, val in all_nearby_stops.items():
            stops[key] = stops.get(key, val)
            stops[key]['_nearby_stop'] = True

        for key, val in all_all_stops.items():
            stops[key] = stops.get(key, val)

        stops_features = []
        for key, val in stops.items():
            props = {k: v for k, v in val.items() if k != 'geometry'}
            f = geojson.Feature(
                id=key, geometry=val['geometry'], properties=props)
            stops_features.append(f)

        routes_features = []
        for key, val in all_routes.items():
            props = {k: v for k, v in val.items() if k != 'geometry'}
            f = geojson.Feature(
                id=key, geometry=val['geometry'], properties=props)
            routes_features.append(f)

        stops_fc = geojson.FeatureCollection(stops_features)
        routes_fc = geojson.FeatureCollection(routes_features)
        return stops_fc, routes_fc

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

    def town_waypoints(self, trail_section=None):
        """Get town waypoints from OSM
        """
        towns = self.towns(trail_section=trail_section)
        osm = data_source.OpenStreetMap()

        all_data = []
        for town in towns.itertuples():
            pois = osm.get_town_pois_for_polygon(town.geometry)
            pois['town_id'] = town.id
            pois['town_name'] = town.name
            all_data.append(pois)

        gdf = gpd.GeoDataFrame(pd.concat(all_data))

        # for row in gdf.itertuples():
        #     self._handle_town_poi(row)

    def _handle_town_poi(self, row):
        """Classify OSM tags into simpler categories
        """
        restaurant_amenities = [
            'bar', 'biergarten', 'fast_food', 'ice_cream', 'pub', 'restaurant'
        ]
        poi_type = None
        poi_details = {}
        if row.amenity in restaurant_amenities:
            poi_type = 'food'
        elif row.amenity in ['cafe']:
            poi_type = 'cafe'
        elif row.amenity in ['atm', 'bank']:
            poi_type = 'bank'
        elif row.amenity in ['clinic', 'hospital']:
            poi_type = 'hospital'
        elif row.amenity in ['pharmacy']:
            poi_type = 'pharmacy'
        elif row.amenity in ['post_office']:
            poi_type = 'post_office'
        elif row.amenity in ['ranger_station']:
            poi_type = 'ranger_station'
        elif row.amenity in ['shower']:
            poi_type = 'shower'
        elif row.amenity in ['toilets']:
            poi_type = 'toilets'
        elif row.amenity in ['drinking_water']:
            poi_type = 'drinking_water'

        isnan(row.cuisine)

    def handle_sections(self, use_cache: bool = True):
        sections = VALID_TRAIL_SECTIONS[self.trail_code]
        for section_name in sections:
            hm_sections = TRAIL_HM_XW[section_name]
            track = self.hm.trail_section(hm_sections, alternates=True)
            wpt = self.hm.wpt_section(hm_sections)

            buf = geom.buffer(track, distance=2, unit='mile').unary_union

            # section =
            # track

            self = TrailSection(
                buffer=buf, section_name=section_name, use_cache=use_cache)
            self.main(wpt=wpt)

            # self.handle_section(wpt=wpt, use_cache=use_cache)


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

    def parse_generated_osm_trail_data(self, nodes, edges, intersections):
        """Iterate over OSM trail data to generate waypoints
        """

        # Mapping from OSM term to term used in description
        # I.e. Join a "dirt road" or "unpaved road"
        surface_tr = {
            'dirt': 'dirt',
            'unpaved': 'unpaved',
            'ground': 'dirt',
            'asphalt': 'paved',
            'paved': 'paved',
        }
        highway_tr = {
            'path': 'trail',
            'bridleway': 'trail',
            'residential': 'road',
            'track': 'road',
            'unclassified': 'road',
            'footway': 'trail',
            'service': 'road',
            'primary': 'road',
            'secondary': 'road',
            'tertiary': 'road',
        }

        data_list = []
        descriptions = {
            'highway=track&surface=unpaved': 'Join unpaved road',
        }

        prev_surface = ''
        prev_way_type = ''

        for edge in edges.itertuples():
            way_type = highway_tr.get(edge.highway)
            assert way_type is not None, 'way_type is undefined'

            # Check type of way
            if way_type != prev_way_type:
                # Trail changed from road to trail or trail to road
                pass

            # Check start node for intersections
            start_node = edge.u

            intersections

            # if (edge.highway != prev_highway):
            #     # Changing from
            #
            # edge

            break

        edges[edges['highway'] == 'unclassified']
        edges[edges['highway'] == 'unclassified']
        intersections[intersections['highway'] == 'secondary']
        edges[(edges['surface'] != 'unpaved') & edges['surface'].notna()]

        edges

        nodes

        edges
        nodes
        intersections

        pass

    def intersect_hydrography(self, trail_line):
        # TODO: pass the trail + alternates
        # TODO pass full OSM path network near trail (take out railways), so
        # that I can find springs or other water sources that are off trail but
        # there's a trail to them, + calculate distance
        trail = gpd.GeoDataFrame([], geometry=[trail_line])
        buffer = gpd.GeoDataFrame([], geometry=[self.buffer])

        hydro = data_source.USGSHydrography()
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

    def _hydro_point(self, hydro, files, buffer):
        point = hydro.read_files(files=files, layer='NHDPoint')

        SPRING = 45800
        WATERFALL = 48700
        WELL = 48800
        keep = [SPRING, WATERFALL]
        point = point[point['FCode'].isin(keep)]

        point = sjoin(point, buffer, how='inner')
        len(point)
        point = to_2d(point)
        point

        point
        if len(point) > 0:
            raise NotImplementedError('Water points near trail')

        areal = hydro.read_files(files=files, layer='NHDArea')
        areal = sjoin(areal, trail, how='inner')
        if len(point) > 0:
            raise NotImplementedError('Areal near trail')

        w_areal = hydro.read_files(files=files, layer='NHDWaterbody')
        w_areal = sjoin(w_areal, trail, how='inner')
        if len(point) > 0:
            raise NotImplementedError('Areal near trail')

        len(w_areal)
        self.buffer

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

    def _track_osm_api(self):
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
        # Set geometry variable so that it can be updated if it needs to be made
        # valid. You can't update a namedtuple
        geometry = row.geometry

        # Check if geometry is valid
        if not geometry.is_valid:
            geometry = geometry.buffer(0)

        # Compute intersection
        int_line = trail.intersection(geometry)

        # Get key_col in dataset
        key = getattr(row, key_col)

        # Instantiate dict with key
        intersections[key] = intersections.get(key, {})

        if int_line.type == 'LineString':
            intersections[key]['geometry'] = MultiLineString([int_line])
        elif int_line.type == 'MultiLineString':
            intersections[key]['geometry'] = int_line
        elif int_line.type == 'GeometryCollection':
            msg = 'If GeometryCollection should not have intersection'
            assert len(int_line) == 0, msg
            intersections[key]['geometry'] = None
        else:
            msg = 'intersection of Polygon, LineString should be LineString'
            raise ValueError(msg)

    # Add length in projected coordinates to dictionary
    for key, d in intersections.items():
        if d['geometry'] is None:
            intersections[key]['length'] = None
            continue

        intersections[key]['length'] = d['geometry'].length

    return intersections


def milemarker_for_points(
        points: List[Point], method: List[str], trail_code='pct'):
    """Find mile marker for point

    Args:
        points: list of shapely point in EPSG 4326
        method: 'line', 'waypoint'
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
