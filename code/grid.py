# Helpers for dealing with irregularly spaced grids

from math import ceil, floor
from typing import Dict, List

import numpy as np
import pint
from shapely.geometry import box

from data import Halfmile

ureg = pint.UnitRegistry()


class TenthDegree:
    """.1 degree grid

    Used for LightningCounts
    """
    def __init__(self):
        pass

    def get_cells(self) -> Dict[str, List[str]]:
        """Find centerpoints of .1 degree cells that PCT passes through

        Lightning data has .1 degree _centerpoints_, so the grid lines are at
        40.05, 40.15, 40.25 etc.

        Create shapely Polygons for each lat/lon quads, then intersect
        with the buffer polygon.

        Returns:
            Dictionary with degree blocks and degree-minute blocks that
            represent quads within 20 miles of trail
        """

        # Load trail line
        trail = Halfmile().trail()
        assert len(trail) == 1, 'Why does gdf have > 1 row?'
        trail_line = trail.geometry[0]

        # Create list of polygon bboxes for quads
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
        centerpoints = [
            list(x.centroid.coords)[0] for x in intersecting_bboxes
        ]
        centerpoints = [(round(coord[0], 1), round(coord[1], 1))
                        for coord in centerpoints]
        return centerpoints
