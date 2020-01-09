"""
Entry point for CLI. CLI code is in the cli/ folder.

See

https://stackoverflow.com/a/39228156
https://github.com/drorata/mwe-subcommands-click

for how to separate a click CLI into subfiles
"""
import click

from cli.data_export import national_parks, wikipedia_for_trail
from cli.photos import copy_using_xw, geotag_photos
from cli.tiles import package_tiles, tiles_for_trail


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


export.add_command(wikipedia_for_trail)
export.add_command(national_parks)


@main.group()
def tiles():
    pass

tiles.add_command(tiles_for_trail)
tiles.add_command(package_tiles)

if __name__ == '__main__':
    main()
