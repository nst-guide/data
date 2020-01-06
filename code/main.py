"""
Entry point for CLI. CLI code is in the cli/ folder.

See

https://stackoverflow.com/a/39228156
https://github.com/drorata/mwe-subcommands-click

for how to separate a click CLI into subfiles
"""
import click

from cli.photos import copy_using_xw, geotag_photos
from cli.tiles import package_tiles


@click.group()
def main():
    pass


main.add_command(package_tiles)
main.add_command(geotag_photos)
main.add_command(copy_using_xw)

if __name__ == '__main__':
    main()
