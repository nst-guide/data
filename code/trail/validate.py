from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize

import geom
from geom import reproject


def area_between_two_lines(
        line1: LineString, line2: LineString, crs=3488) -> float:
    """Compute area between two lines

    It's important to check how accurate the OSM track is compared to other
    tracks. So here I use two provided lines to create the polygons that
    make up the area between the two lines, then I add those areas
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
    # Reproject lines to projected coordinate system
    line1 = reproject(line1, geom.WGS84, crs)
    line2 = reproject(line2, geom.WGS84, crs)

    # Check that lines are in the same direction
    # Get distance between start point of each line, then assert they're
    # within 1000m
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
