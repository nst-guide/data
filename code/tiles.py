import json
import re
from math import ceil, floor
from pathlib import Path
from subprocess import run
from typing import Dict, List, Tuple
from urllib.parse import urljoin
from urllib.request import urlretrieve

import numpy as np
import pint
import requests
from bs4 import BeautifulSoup
from shapely.geometry import Polygon, box, mapping

from data_source import DataSource, Halfmile

ureg = pint.UnitRegistry()


class FSTopo:
    """Forest Service topo maps
    """
    def __init__(self):
        pass

    def generate_tiles(self):
        blocks_dict = self.get_quads()
        tif_urls = self.find_urls(blocks_dict)
        fs_tiles_dir = self.download_tifs(tif_urls)
        self.tifs_to_tiles(tile_dir=fs_tiles_dir)

    def get_quads(self) -> Dict[str, List[str]]:
        """Find FSTopo quad files

        FSTopo is a 7.5-minute latitude/longitude grid system. Forest service
        files are grouped into 5-digit _blocks_, which correspond to the degree
        of latitude and longitude. For example, [block 46121][block_46121]
        contains all files that are between latitude 46° and 47° and longitude
        -121° to longitude -122°. Within that, each latitude and longitude
        degree is split into 7.5' segments. This means that there are 8 cells
        horizontally and 8 cells vertically, for up to 64 total quads within
        each lat/lon block. FSTopo map quads are only created for National
        Forest areas, so not every lat/lon block has 64 files.

        Idea: Create shapely Polygons for each lat/lon quads, then intersect
        with the buffer polygon.

        Returns:
            Dictionary with degree blocks and degree-minute blocks that
            represent quads within 20 miles of trail

        [block_46121]: https://data.fs.usda.gov/geodata/rastergateway/states-regions/quad-index.php?blockID=46121
        """

        # Load trail buffer
        buffer_polygon = Halfmile().buffer_full(distance=20)

        # Create list of polygon bboxes for quads
        bounds = buffer_polygon.bounds

        # Get whole-degree bounding box of `bounds`
        minx, miny, maxx, maxy = bounds
        minx, miny = floor(minx), floor(miny)
        maxx, maxy = ceil(maxx), ceil(maxy)

        # 7.5 minutes is 1/8 degree
        # maxx, maxy not included in list, but when generating polygons, will
        # add .125 for x and y, and hence maxx, maxy will be upper corner of
        # last bounding box.
        # ll_points: lower left points of bounding boxes
        stepsize = 0.125
        ll_points = []
        for x in np.arange(minx, maxx, stepsize):
            for y in np.arange(miny, maxy, stepsize):
                ll_points.append((x, y))

        intersecting_bboxes = []
        for ll_point in ll_points:
            ur_point = (ll_point[0] + stepsize, ll_point[1] + stepsize)
            bbox = box(*ll_point, *ur_point)
            if bbox.intersects(buffer_polygon):
                intersecting_bboxes.append(bbox)

        # The FS website directory goes by lat/lon boxes, so I need to get the
        # whole-degree boxes
        # FS uses the min for lat, max for lon, aka 46121 has quads with lat >=
        # 46 and lon <= -121
        blocks_dict = {}
        for intersecting_bbox in intersecting_bboxes:
            bound = intersecting_bbox.bounds
            miny = bound[1]
            maxx = bound[2]
            degree_y = str(floor(miny))
            degree_x = str(abs(ceil(maxx)))

            decimal_y = miny % 1
            minute_y = str(
                floor((decimal_y * ureg.degree).to(ureg.arcminute).magnitude))
            # Left pad to two digits
            minute_y = minute_y.zfill(2)

            decimal_x = maxx % 1
            minute_x = str(
                floor((decimal_x * ureg.degree).to(ureg.arcminute).magnitude))
            # Left pad to two digits
            minute_x = minute_x.zfill(2)

            degree_block = degree_y + degree_x
            minute_block = degree_y + minute_y + degree_x + minute_x

            blocks_dict[degree_block] = blocks_dict.get(degree_block, [])
            blocks_dict[degree_block].append(minute_block)

        return blocks_dict

    def find_urls(self, blocks_dict):
        """Find urls for FS Topo tif files near trail
        """
        all_tif_urls = []
        for degree_block_id, minute_quad_ids in blocks_dict.items():
            block_url = 'https://data.fs.usda.gov/geodata/rastergateway/'
            block_url += 'states-regions/quad-index.php?'
            block_url += f'blockID={degree_block_id}'
            r = requests.get(block_url)
            soup = BeautifulSoup(r.content)
            links = soup.select('#skipheader li a')

            # Not sure what happens if the blockID page doesn't exist on the FS
            # website. Apparently internal server error from trying 99999
            if links:
                # Keep only quads that were found to be near trail
                links = [
                    link for link in links if link.text[:9] in minute_quad_ids
                ]
                urls = [urljoin(block_url, link.get('href')) for link in links]
                tif_urls = [url for url in urls if url[-4:] == '.tif']
                all_tif_urls.extend(tif_urls)

        return all_tif_urls

    def download_tifs(self, tif_urls: List[str], overwrite: bool = False):
        """Download FSTopo tif files to local storage

        Args:
            tif_urls: list of urls to tif quads on Forest Service website
            overwrite: whether to overwrite currently-downloaded tif files
        """
        data_dir = DataSource().data_dir
        fs_tiles_dir = data_dir / 'pct' / 'tiles' / 'fstopo'
        fs_tiles_dir.mkdir(exist_ok=True, parents=True)

        for tif_url in tif_urls:
            name = Path(tif_url).name
            local_path = fs_tiles_dir / name
            if overwrite or (not local_path.exists()):
                urlretrieve(tif_url, local_path)

        return fs_tiles_dir

    def tifs_to_tiles(self, tile_dir, n_processes=8, resume=False):
        """Convert tifs to tiles

        So far, I've only run these commands in the shell. Need to test from
        Python.
        """
        raise NotImplementedError("Haven't tested this code from Python yet")

        tif_files = tile_dir.glob('*.tif')
        vrt_path = tile_dir / 'mosaic.vrt'

        # Create virtual mosaic of connected quad tifs
        cmd = ['gdalbuildvrt', vrt_path, *tif_files]
        run(cmd, check=True)

        # Expand into rgba
        # gdal_translate -of vrt -expand rgba output.vrt expanded.vrt
        rgba_path = tile_dir / 'rgba.vrt'
        cmd = [
            'gdal_translate', '-of', 'vrt', '-expand', 'rgba', vrt_path,
            rgba_path
        ]
        run(cmd, check=True)

        # Split into tiles
        # Make sure you call my fork of `gdal2tiles.py` that sets the image size
        # to 512
        cmd = [
            'gdal2tiles.py', rgba_path, f'--processes={n_processes}',
            '--srcnodata="0,0,0,0"'
        ]
        if resume:
            cmd.append('--resume')
        run(cmd, check=True)


def tiles_for_polygon(polygon: Polygon, zoom_levels) -> List[Tuple[int]]:
    """Generate x,y,z tile tuples for polygon

    Args:
        - polygon: polygon to generate tiles for
        - zoom_levels: iterable with integers for zoom levels
    """
    stdin = json.dumps(mapping(polygon))

    xyz_tuples = []
    for zoom_level in zoom_levels:
        cmd = ['supermercado', 'burn', str(zoom_level)]
        r = run(cmd, capture_output=True, input=stdin, encoding='utf-8')
        xyz_tuples.extend(r.stdout.strip().split('\n'))

    regex = re.compile(r'\[(\d+), (\d+), (\d+)\]')
    xyz_tuples = [tuple(map(int, regex.match(s).groups())) for s in xyz_tuples]
    return xyz_tuples


def geojson_for_tiles(tile_tuples: List[Tuple[int]]) -> str:
    """Generate GeoJSON for list of map tile tuples

    Args:
        - tile_tuples: list of (x, y, z) tuples
    """
    stdin = '\n'.join([f'[{x}, {y}, {z}]' for x, y, z in tile_tuples])

    cmd = ['mercantile', 'shapes']
    r = run(cmd, capture_output=True, input=stdin, encoding='utf-8')

    cmd = ['fio', 'collect']
    r = run(cmd, capture_output=True, input=r.stdout, encoding='utf-8')

    return r.stdout
