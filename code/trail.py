import fiona
import geopandas as gpd
import pandas as pd
from geopandas.tools import sjoin

import data
from data import Halfmile, Towns
from geom import buffer


class Trail:
    def __init__(self):
        pass


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