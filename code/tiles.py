import json
import re
from math import ceil, floor
from operator import itemgetter
from pathlib import Path
from subprocess import run
from typing import Dict, List, Tuple
from urllib.parse import urljoin
from urllib.request import urlretrieve

import geopandas as gpd
import pint
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse
from geopandas.tools import sjoin
from shapely.geometry import MultiPolygon, Polygon, box, mapping

import grid
from geom import round_geometry

from .data_source import DataSource, MapIndices, NationalMapAPI
from .s3 import upload_directory_to_s3

ureg = pint.UnitRegistry()


class FSTopo(DataSource):
    """Forest Service topo maps
    """
    def __init__(self):
        super(FSTopo, self).__init__()
        self.tiles_dir = self.data_dir / 'pct' / 'tiles' / 'fstopo'
        self.tiles_dir.mkdir(exist_ok=True, parents=True)

    def generate_tiles(self, geom):
        """
        Args:
            - geom: geometry to find quadrangle intersections with
        """
        blocks_dict = self.get_quads(geom)
        tif_urls = self.find_urls(blocks_dict)
        self.download_tifs(
            tif_urls, download_dir=self.tiles_dir, overwrite=False)
        tile_dir = tifs_to_tiles(tif_dir=self.tiles_dir)
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

    def download_tifs(self, tif_urls: List[str], overwrite: bool = False):
        """Download FSTopo tif files to local storage

        Args:
            tif_urls: list of urls to tif quads on Forest Service website
            overwrite: whether to overwrite currently-downloaded tif files
        """
        fs_tiles_dir = self.data_dir / 'pct' / 'tiles' / 'fstopo'
        fs_tiles_dir.mkdir(exist_ok=True, parents=True)

        for tif_url in tif_urls:
            name = Path(tif_url).name
            local_path = fs_tiles_dir / name
            if overwrite or (not local_path.exists()):
                urlretrieve(tif_url, local_path)

        return fs_tiles_dir


class NAIPImagery(DataSource):
    """docstring for NAIPImagery"""
    def __init__(self):
        super(NAIPImagery, self).__init__()
        self.tiles_dir = self.data_dir / 'pct' / 'tiles' / 'naip'
        self.tiles_dir.mkdir(exist_ok=True, parents=True)

    def generate_tiles(self, geom):
        """
        Should set buffer set to 2 miles around HM for now. That's like 30GB of
        data as it is.

        Args:
            - geom: geometry to find quadrangle intersections with
        """
        urls = self.get_urls(geom)
        download_urls(urls=urls, download_dir=self.tiles_dir, overwrite=False)

    def get_urls(self, geom):
        """Get NAIP download urls for geometry

        Args:
            - geom: geometry to get urls for

        Returns:
            - list of urls to download
        """
        # Get quad indices; intersect with the provided geometry
        indices = MapIndices().read(layer='3_75Minute')
        gdf = gpd.GeoDataFrame(geometry=[geom])
        intersection = sjoin(indices, gdf, how='inner')

        # For each intersecting box,
        api = NationalMapAPI()
        urls = []
        for bbox in intersection.geometry:
            # bbox from MapIndices has some floating point deviations so need to
            # round the geometry to find the matching item from the API request
            bbox = round_geometry(bbox, digits=4)

            if isinstance(bbox, MultiPolygon):
                msg = 'More than one item in MultiPolygon'
                assert len(bbox) == 1, msg
                bbox = bbox[0]
            elif isinstance(bbox, Polygon):
                pass
            else:
                msg = 'Map Index geometry is not Polygon'
                raise ValueError(msg)

            res = api.search_products(bbox=bbox, product_name='naip')
            url = self._find_url_from_result(bbox=bbox, res=res)
            urls.append(url)

        return urls

    def _find_url_from_result(self, bbox, res):
        """From the API results, find the exact file requested
        """
        matches = [item for item in res['items'] if item['bestFitIndex'] == 1.0]
        if len(matches) == 1:
            return matches[0]['downloadURL']

        # Choose the most recent image if there are more than one
        dates = [parse(item['dateCreated']) for item in matches]
        idx = max(enumerate(dates), key=itemgetter(1))[0]
        return matches[idx]['downloadURL']

    def _item_geom(self, item):
        return box(
            item['boundingBox']['minX'], item['boundingBox']['minY'],
            item['boundingBox']['maxX'], item['boundingBox']['maxY'])


def download_urls(self, urls: List[str], download_dir, overwrite: bool = False):
    """Download tif files to local storage

    Args:
        urls: list of urls to download
        overwrite: whether to overwrite currently-downloaded tif files
    """
    download_dir.mkdir(exist_ok=True, parents=True)
    for url in urls:
        name = Path(url).name
        local_path = download_dir / name
        if overwrite or (not local_path.exists()):
            urlretrieve(url, local_path)


def tifs_to_tiles(tif_dir, n_processes=8, resume=False):
    """Convert tifs to tiles

    So far, I've only run these commands in the shell. Need to test from Python.

    Shell commands for working transparency:
    ```
    # Call gdalbuildvrt with -addalpha.
    # > Adds an alpha mask band to the VRT when the source raster have none. The
    # > alpha band is filled on-the-fly with the value 0 in areas without any
    # > source raster, and with value 255 in areas with source raster. The
    # > effect is that a RGBA viewer will render the areas without source
    # > rasters as transparent and areas with source rasters as opaque.
    gdalbuildvrt -addalpha mosaic.vrt *.tif

    # Use gdal_translate to take the single band with color table and expand it
    # into a 3-band VRT
    gdal_translate -of vrt -expand rgb mosaic.vrt rgb.vrt

    # Split the three rgb bands from rgb.vrt into separate files. This is
    # because I need to merge these rgb bands with the transparency band that's
    # the second band of mosaic.vrt from `gdalbuildvrt`, and I don't know how to
    # do that without separating bands into individual VRTs and then merging
    # them.
    gdal_translate -b 1 rgb.vrt r.vrt
    gdal_translate -b 2 rgb.vrt g.vrt
    gdal_translate -b 3 rgb.vrt b.vrt
    gdal_translate -b 2 mosaic.vrt a.vrt

    # Merge the four bands back together
    gdalbuildvrt -separate rgba.vrt r.vrt g.vrt b.vrt a.vrt

    # Any raster cell where the fourth band is 0 should be transparent. I
    # couldn't figure out how to declare that all such data should be considered
    # nodata, but from inspection it looks like those areas have rgb values of
    # 54, 52, 52
    # This process is still better than just declaring 54, 52, 52 to be nodata
    # in a plain rgb file, in case there is any actual data in the map that's
    # defined as this rgb trio
    ./gdal2tiles.py rgba.vrt --processes 16 --srcnodata="54,52,52,0" --exclude
    ```
    # TODO: update below Python code to reflect the above bash commands.
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

    stdin = json.dumps(mapping(polygon))

    tile_tuples = []
    for zoom_level in zoom_levels:
        cmd = ['supermercado', 'burn', str(zoom_level)]
        r = run(cmd, capture_output=True, input=stdin, encoding='utf-8')
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
