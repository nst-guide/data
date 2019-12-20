import json
import re
from subprocess import run
from typing import List, Tuple

from shapely.geometry import Polygon, mapping

from geom import to_2d


def tiles_for_polygon(polygon: Polygon, zoom_levels,
                      scheme='xyz') -> List[Tuple[int]]:
    """Generate x,y,z tile tuples for polygon

    Args:
        - polygon: polygon to generate tiles for
        - zoom_levels: iterable with integers for zoom levels
        - scheme: scheme of output tuples, either "xyz" or "tms"
    """
    if scheme not in ['xyz', 'tms']:
        raise ValueError('scheme must be "xyz" or "tms"')

    # Supermercado gets upset with 3D coordinates
    stdin = json.dumps(mapping(to_2d(polygon)))

    tile_tuples = []
    for zoom_level in zoom_levels:
        cmd = ['supermercado', 'burn', str(zoom_level)]
        r = run(
            cmd, capture_output=True, input=stdin, check=True, encoding='utf-8')
        tile_tuples.extend(r.stdout.strip().split('\n'))

    regex = re.compile(r'\[(\d+), (\d+), (\d+)\]')
    tile_tuples = [
        tuple(map(int,
                  regex.match(s).groups())) for s in tile_tuples
    ]

    if scheme == 'tms':
        tile_tuples = [xyz_to_tms(x, y, z) for x, y, z in tile_tuples]

    return tile_tuples


def geojson_from_tiles(tile_tuples: List[Tuple[int]], scheme='xyz') -> str:
    """Generate GeoJSON for list of map tile tuples

    Args:
        - tile_tuples: list of (x, y, z) tuples
        - scheme: scheme of input tuples, either "xyz" or "tms"
    Returns:
        GeoJSON FeatureCollection of covered tiles
    """
    if scheme == 'xyz':
        pass
    elif scheme == 'tms':
        tile_tuples = [tms_to_xyz(x, y, z) for x, y, z in tile_tuples]
    else:
        raise ValueError('scheme must be "xyz" or "tms"')

    stdin = '\n'.join([f'[{x}, {y}, {z}]' for x, y, z in tile_tuples])

    cmd = ['mercantile', 'shapes']
    r = run(cmd, capture_output=True, input=stdin, encoding='utf-8')

    cmd = ['fio', 'collect']
    r = run(cmd, capture_output=True, input=r.stdout, encoding='utf-8')

    return r.stdout


def switch_xyz_tms(x, y, z):
    """Switch between xyz and tms coordinates

    https://gist.github.com/tmcw/4954720
    """
    y = (2 ** z) - y - 1
    return x, y, z


def xyz_to_tms(x, y, z):
    return switch_xyz_tms(x, y, z)


def tms_to_xyz(x, y, z):
    return switch_xyz_tms(x, y, z)
