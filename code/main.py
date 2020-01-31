"""
Entry point for CLI. CLI code is in the cli/ folder.

See

https://stackoverflow.com/a/39228156
https://github.com/drorata/mwe-subcommands-click

for how to separate a click CLI into subfiles
"""
import click

from cli.data_export import (
    national_forests, national_parks, town_boundaries, wikipedia, wilderness,
    wildfire_historical)
from cli.geom import polylabel
from cli.photos import copy_using_xw, geotag_photos
from cli.tiles import package_tiles, tiles_for_trail
from cli.util import metadata_json_to_tile_json


@click.group()
def main():
    pass


@main.group()
def photos():
    pass


photos.add_command(geotag_photos)
photos.add_command(copy_using_xw)


@main.group()
def export():
    pass


export.add_command(national_forests)
export.add_command(national_parks)
export.add_command(town_boundaries)
export.add_command(wikipedia)
export.add_command(wilderness)
export.add_command(wildfire_historical)


@main.group()
def tiles():
    pass


tiles.add_command(tiles_for_trail)
tiles.add_command(package_tiles)


@main.group()
def geom():
    pass


geom.add_command(polylabel)


@main.group()
def util():
    pass


util.add_command(metadata_json_to_tile_json)

if __name__ == '__main__':
    main()
