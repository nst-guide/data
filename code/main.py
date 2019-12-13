import click

from .package_tiles import package_tiles as _package_tiles


@click.group()
def main():
    pass


@main.command()
@click.option(
    '-g',
    '--geometry',
    multiple=True,
    required=True,
    type=click.Path(
        exists=True, file_okay=True, dir_okay=False, resolve_path=True),
    help=
    'Geometries to use for packaging tiles. Can be any format readable by GeoPandas.'
)
@click.option(
    '-b',
    '--buffer',
    multiple=True,
    required=True,
    help=
    'Buffer distance (in miles) to use around provided geometries. The same number of options as geometry must be provided. If you want multiple buffer distances, pass as --buffer "2 5 10"'
)
@click.option(
    '-d',
    '--directory',
    type=click.Path(
        exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    required=True,
    multiple=True,
    help=
    'Directory root of tiles to package. If multiple options are provided, will package each of them.'
)
@click.option(
    '-t',
    '--tile-json',
    type=click.Path(
        exists=True, file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    multiple=True,
    help=
    'Paths to tile.json files for each directory. If not provided, assumes a tile JSON file is at directory/tile.json. Otherwise, the same number of options as directory must be provided.'
)
@click.option(
    '-o',
    '--output',
    type=click.Path(exists=False, writable=True, resolve_path=True),
    required=True,
    help='Output path')
@click.option(
    '--raise/--no-raise',
    'raise_errors',
    default=True,
    help=
    'Whether to raise an error if a desired tile is not found in the directory.'
)
def package_tiles(geometry, buffer, directory, tile_json, output, raise_errors):
    """Package tiles into zip based on distance from trail

    Example:
    python main.py package-tiles -g ../data/pct/polygon/bound/town/ca/acton.geojson -b "0 1 2" -d ~/Desktop -o out.zip
    """
    # Make sure that buffer and geometry have same dimensions
    msg = 'geometry and buffer must be provided the same number of times'
    assert len(geometry) == len(buffer), msg

    # Make sure that buffer and geometry have same dimensions
    if tile_json:
        msg = 'tile-json and directory must be provided the same number of times'
        assert len(geometry) == len(buffer), msg

    _package_tiles(
        geometry=geometry,
        buffer=buffer,
        directory=directory,
        tile_json=tile_json,
        output=output,
        raise_errors=raise_errors)


if __name__ == '__main__':
    main()
