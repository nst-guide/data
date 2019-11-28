import sys

from shapely.geometry import Polygon

import tiles

sys.path.append('../code')


def test_cell():
    """
    Testing 485212052_Skagit_Peak_FSTopo.tif
    """
    cell = [
        (-120.875, 48.875),
        (-120.875, 49),
        (-121.0, 49),
        (-121.0, 48.875),
        (-120.875, 48.875)] # yapf: disable
    cell = Polygon(cell)
    blocks_dict = tiles.create_blocks_dict([cell])
    assert blocks_dict == {'48120': ['485212052']}
