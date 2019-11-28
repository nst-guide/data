import json
import re
from math import ceil, floor
from pathlib import Path
from subprocess import run
from typing import Dict, List, Tuple
from urllib.parse import urljoin
from urllib.request import urlretrieve

import pint
import requests
from bs4 import BeautifulSoup
from shapely.geometry import Polygon, mapping

import grid
from s3 import upload_directory_to_s3

ureg = pint.UnitRegistry()


class FSTopo:
    """Forest Service topo maps
    """
    def __init__(self):
        pass

    def generate_tiles(self, geom):
        blocks_dict = self.get_quads(geom)
        tif_urls = self.find_urls(blocks_dict)
        fs_tiles_dir = self.download_tifs(tif_urls)
        tile_dir = tifs_to_tiles(tif_dir=fs_tiles_dir)
        upload_directory_to_s3(
            tile_dir,
            bucket_path='fstopo',
            bucket_name='tiles.nst.guide',
            content_type='image/png')

    def get_quads(self, geom) -> Dict[str, List[str]]:
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

        Returns:
            Dictionary with degree blocks and degree-minute blocks that
            represent quads within 20 miles of trail

        [block_46121]: https://data.fs.usda.gov/geodata/rastergateway/states-regions/quad-index.php?blockID=46121
        """
        topo_grid = grid.TopoQuadGrid(geom)
        return self.create_blocks_dict(topo_grid.cells)

    def create_blocks_dict(self, cells):
        """
        The FS website directory goes by lat/lon boxes, so I need to get the
        whole-degree boxes

        FS uses the min for lat, max for lon, aka 46121 has quads with lat >= 46
        and lon <= -121
        """
        blocks_dict = {}
        for cell in cells:
            miny, maxx = cell.bounds[1:3]
            degree_y = str(floor(miny))
            degree_x = str(abs(ceil(maxx)))

            decimal_y = abs(miny) % 1
            minute_y = str(
                floor((decimal_y * ureg.degree).to(ureg.arcminute).magnitude))
            # Left pad to two digits
            minute_y = minute_y.zfill(2)

            # Needs to be abs because otherwise the mod of a negative number is
            # opposite of what I want.
            decimal_x = abs(maxx) % 1
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

        Args:
            - blocks_dict: {header: [all_values]}, e.g. {'41123': ['413012322']}
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

    def download_tifs(
            self, data_dir, tif_urls: List[str], overwrite: bool = False):
        """Download FSTopo tif files to local storage

        Args:
            tif_urls: list of urls to tif quads on Forest Service website
            overwrite: whether to overwrite currently-downloaded tif files
        """
        fs_tiles_dir = data_dir / 'pct' / 'tiles' / 'fstopo'
        fs_tiles_dir.mkdir(exist_ok=True, parents=True)

        for tif_url in tif_urls:
            name = Path(tif_url).name
            local_path = fs_tiles_dir / name
            if overwrite or (not local_path.exists()):
                urlretrieve(tif_url, local_path)

        return fs_tiles_dir


def tifs_to_tiles(tif_dir, n_processes=8, resume=False):
    """Convert tifs to tiles

    So far, I've only run these commands in the shell. Need to test from Python.
    """
    raise NotImplementedError("Haven't tested this code from Python yet")

    tif_files = tif_dir.glob('*.tif')
    vrt_path = tif_dir / 'mosaic.vrt'

    # Create virtual mosaic of connected quad tifs
    cmd = ['gdalbuildvrt', vrt_path, *tif_files]
    run(cmd, check=True)

    # Expand into rgba
    # gdal_translate -of vrt -expand rgba output.vrt expanded.vrt
    rgba_path = tif_dir / 'rgba.vrt'
    cmd = [
        'gdal_translate', '-of', 'vrt', '-expand', 'rgba', vrt_path, rgba_path
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
    tile_dir = tif_dir / 'rgba'
    return tile_dir


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
