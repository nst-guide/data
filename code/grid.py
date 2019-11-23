# Helpers for dealing with irregularly spaced grids

from math import ceil, floor
from typing import Dict, List

import geopandas as gpd
import numpy as np
import pint
from shapely.geometry import box

ureg = pint.UnitRegistry()


class OneDegree:
    """1 degree grid

    Used for accessing elevation data
    """
    def __init__(self):
        pass

    def get_cells(self, trail: gpd.GeoDataFrame) -> Dict[str, List[str]]:
        """Find boundaries of 1 degree cells that PCT passes through

        The elevation datasets are identified by the _UPPER_ latitude and
        _LOWER_ longitude, i.e. max and min repsectively

        Create shapely Polygons for each lat/lon quads, then intersect
        with the buffer polygon.

        Args:
            trail_line: LineString representing PCT

        Returns:
            Dictionary with degree blocks and degree-minute blocks that
            represent quads within 20 miles of trail
        """
        # Create list of polygon bboxes for quads
        trail_line = trail.unary_union
        bounds = trail_line.bounds

        # Get whole-degree bounding box of `bounds`
        minx, miny, maxx, maxy = bounds
        minx, miny = floor(minx), floor(miny)
        maxx, maxy = ceil(maxx), ceil(maxy)

        # maxx, maxy not included in list, but when generating polygons, will
        # add .1 for x and y, and hence maxx, maxy will be upper corner of
        # last bounding box.
        # ll_points: lower left points of bounding boxes

        # How big the cells are (i.e. 1 degree, .5 degree, or .1 degree)
        stepsize = 1
        # Non-zero when looking for centerpoints, i.e. for lightning strikes
        # data where the labels are by the centerpoints of the cells, not the
        # bordering lat/lons
        offset = 0

        ll_points = []
        for x in np.arange(minx - offset, maxx + offset, stepsize):
            for y in np.arange(miny - offset, maxy + offset, stepsize):
                ll_points.append((x, y))

        intersecting_bboxes = []
        for ll_point in ll_points:
            ur_point = (ll_point[0] + stepsize, ll_point[1] + stepsize)
            bbox = box(*ll_point, *ur_point)
            if bbox.intersects(trail_line):
                intersecting_bboxes.append(bbox)

        return intersecting_bboxes


class TenthDegree:
    """.1 degree grid

    Used for LightningCounts
    """
    def __init__(self):
        pass

    def get_cells(self, trail: gpd.GeoDataFrame) -> Dict[str, List[str]]:
        """Find centerpoints of .1 degree cells that PCT passes through

        Lightning data has .1 degree _centerpoints_, so the grid lines are at
        40.05, 40.15, 40.25 etc.

        Create shapely Polygons for each lat/lon quads, then intersect
        with the buffer polygon.

        Args:
            trail_line: LineString representing PCT

        Returns:
            Dictionary with degree blocks and degree-minute blocks that
            represent quads within 20 miles of trail
        """
        # Create list of polygon bboxes for quads
        trail_line = trail.unary_union
        bounds = trail_line.bounds

        # Get whole-degree bounding box of `bounds`
        minx, miny, maxx, maxy = bounds
        minx, miny = floor(minx), floor(miny)
        maxx, maxy = ceil(maxx), ceil(maxy)

        # maxx, maxy not included in list, but when generating polygons, will
        # add .1 for x and y, and hence maxx, maxy will be upper corner of
        # last bounding box.
        # ll_points: lower left points of bounding boxes
        stepsize = 0.1
        ll_points = []
        for x in np.arange(minx - .05, maxx + .05, stepsize):
            for y in np.arange(miny - .05, maxy + .05, stepsize):
                ll_points.append((x, y))

        intersecting_bboxes = []
        for ll_point in ll_points:
            ur_point = (ll_point[0] + stepsize, ll_point[1] + stepsize)
            bbox = box(*ll_point, *ur_point)
            if bbox.intersects(trail_line):
                intersecting_bboxes.append(bbox)

        # Find center points and round to nearest .1
        centerpoints = [list(x.centroid.coords)[0] for x in intersecting_bboxes]
        centerpoints = [(round(coord[0], 1), round(coord[1], 1))
                        for coord in centerpoints]
        return centerpoints
