"""
## package_tiles.py

Package tiles into Zip file
"""

import logging
import shutil
import sys
from pathlib import Path

import geopandas as gpd

from geom import buffer
from tiles import tiles_for_polygon

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
Log = logging.getLogger()


def temp():
    geometry_path = '/Users/kyle/github/mapping/nst-guide/create-database/data/pct/line/halfmile/CA_Sec_A_tracks.geojson'
    buffer_dists = (2, 5, 10)
    directory = (
        '/Users/kyle/github/mapping/nst-guide/openmaptiles/ca_or_wa/', )
    tile_jsons = (
        '/Users/kyle/github/mapping/nst-guide/openmaptiles/tile.json', )
    out_dir = 'tmp_out'
    min_zooms = (0, )
    max_zooms = (14, )


def package_tiles(
        geometry_path,
        buffer_dists,
        src_dirs,
        tile_jsons,
        min_zooms,
        max_zooms,
        out_dir,
        raise_errors,
        verbose=False):
    """Package tiles into directory

    TODO: TMS? Index of files pointed to by each buffer?

    For each geometry-buffer pair

    Args:
        - geometry: path to GeoPandas-readable datasets defining the geometry
        - buffer_dists: tuple of distances in miles around geometry. I.e.
          [[2, 5, 10], [0]]
        - directories: iterable of paths to tile directories
        - tile_json: iterable of paths to tile JSON specifications. If empty,
          assumed to be at directory/tile.json.
        - min_zoom: iterable of int representing min zoom for each tile layer
        - max_zoom: iterable of int representing max zoom for each tile layer
        - out_dir: directory for output, directory shouldn't exist
        - raise_errors: whether to raise errors if a requested tile doesn't
          exist. I.e. might not have some tiles for the few miles in
          Canada or buffer in Mexico
    """
    # Make sure output dir doesn't exist yet
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(exist_ok=False, parents=True)

    # Load geometry:
    gdf = gpd.read_file(geometry_path)

    # Get tile indices
    tile_indices_dict = get_tile_indices(gdf, buffer_dists, max_zooms)

    # For each buffer distance, package all files into directory
    for buffer_dist, tile_indices in tile_indices_dict.items():
        if verbose:
            Log.info(f'Running for buffer_dist={buffer_dist}')

        out_dir_this = out_dir / f'{buffer_dist:.0f}'
        out_dir_this.mkdir(parents=True, exist_ok=False)
        _copy_tiles(
            dest_dir=out_dir_this,
            tile_indices=tile_indices,
            src_dirs=src_dirs,
            tile_jsons=tile_jsons,
            min_zooms=min_zooms,
            max_zooms=max_zooms,
            raise_errors=raise_errors,
            verbose=verbose)


def get_tile_indices(gdf, buffer_dists, max_zoom):
    """Generate nested tile indices

    For a given GeoDataFrame, generate tile coordinates for each buffer
    distance. These tile coordinates should include include the difference
    between the current buffer distance and the smaller buffer distance, so that
    the tile coordinates can nest.
    """
    # Generate buffers around geometry and generate tile indices for that
    # geometry
    tile_indices = {}
    for buffer_dist in buffer_dists:
        if buffer_dist > 0:
            buf = buffer(gdf, distance=buffer_dist, unit='mile').unary_union
        else:
            buf = gdf.unary_union

        tiles = tiles_for_polygon(buf, zoom_levels=range(0, max(max_zoom) + 1))
        tile_indices[buffer_dist] = tiles

    # When multiple buffer distances are provided, change the higher values to
    # be the difference in tiles between it and the next lowest buffer. So if
    # the buffer distances provided are [2, 5, 10], then change tile_indices[5]
    # to contain only the tile coordinates not in tile_indices[2]
    #
    # NOTE: make sure you create a new dict, otherwise, if you start at the
    # bottom, when you're comparing buffer 5 and buffer 10, you might
    # unintentionally take the set difference of 10 and (5 diff 2), which would
    # include the original 2-buffer tiles. Either start at the largest dist, or
    # you have to diff every lower value, or create a new dict...
    buffer_dists = sorted(buffer_dists)
    if len(buffer_dists) > 1:
        tile_indices_new = {}
        tile_indices_new[min(buffer_dists)] = tile_indices[min(buffer_dists)]
        for prev_dist, dist in zip(buffer_dists, buffer_dists[1:]):
            tile_indices_new[dist] = set(tile_indices[dist]).difference(
                tile_indices[prev_dist])

        tile_indices = tile_indices_new

    # tile_indices now has the minimum tile coordinates for each zoom level
    return tile_indices


def _copy_tiles(
        dest_dir,
        tile_indices,
        src_dirs,
        tile_jsons,
        min_zooms,
        max_zooms,
        raise_errors,
        verbose=False,
        ext=None):
    """Copy tiles to output directory

    Args:
        - dest_dir: directory to move files to
        - tile_indices: list of tuples for files to move
        - src_dirs: source directories
        - tile_jsons: source tile JSON specs
        - min_zooms: min zoom for each source dir
        - max_zooms: max zoom for each source dir
        - raise_errors: if True, raises an error if the source file doesn't exist
        - ext: extensions to copy. If None, copies all files with x/y/z order. Should be a string.
    """
    if ext is not None:
        ext = '.' + ext.lstrip('.')

    if not tile_jsons:
        tile_jsons = [None] * len(src_dirs)

    for src_dir, tile_json, min_zoom, max_zoom in zip(src_dirs, tile_jsons,
                                                      min_zooms, max_zooms):
        # Destination folder name should have an identifier:
        # I.e. you want 2/openmaptiles/{z}/{x}/{y}.ext
        # For now I'll get the name from the source dir
        tiledir_name = Path(src_dir).name
        if verbose:
            Log.info(f'copying from src_dir={src_dir}')
            Log.info(f'to dest_dir={dest_dir / tiledir_name}')

        # Get indices within min zoom and max zoom
        filtered_indices = [
            x for x in tile_indices if (x[2] >= min_zoom) & (x[2] <= max_zoom)
        ]
        for x, y, z in filtered_indices:
            _copy_tile(
                src_dir=src_dir,
                dest_dir=dest_dir / tiledir_name,
                x=x,
                y=y,
                z=z,
                raise_errors=raise_errors,
                ext=ext)

        # Also copy the tile.json
        # If tile_json is None, it's assumed to be
        if tile_json is None:
            tile_json = Path(src_dir) / 'tile.json'

        try:
            shutil.copy(tile_json, dest_dir / tiledir_name / 'tile.json')
        except FileNotFoundError:
            print('Warning: could not find tile_json file')


def _copy_tile(src_dir, dest_dir, x, y, z, raise_errors, ext=None):
    """Copy individual tile from src_dir to dest_dir

    Args:
        - raise_errors: if True, raises an error when a file is not found
    """
    src = Path(src_dir) / str(z) / str(x)
    if ext is not None:
        src = src / f'{y}{ext}'
    else:
        try:
            src = list(src.glob(f'{y}*'))[0]
        except IndexError:
            if raise_errors:
                raise FileNotFoundError(src / f'{z}*')
            else:
                return

    # Use src.name instead of z to keep the correct file extension
    dest = Path(dest_dir) / str(z) / str(x) / src.name
    dest.parents[0].mkdir(exist_ok=True, parents=True)

    shutil.copy(src, dest)
