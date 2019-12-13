import click


@click.group()
def main():
    pass


@main.command()
@click.option(
    '-g',
    '--geometry',
    multiple=True,
    required=True,
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
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    required=True,
    multiple=True,
    help=
    'Directory root of tiles to package. If multiple options are provided, will package each of them.'
)
@click.option(
    '-t',
    '--tile-json',
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    required=False,
    multiple=True,
    help=
    'Paths to tile.json files for each directory. If not provided, assumes a tile JSON file is at directory/tile.json. Otherwise, the same number of options as directory must be provided.'
)
@click.option(
    '-o',
    '--output',
    type=click.Path(exists=False, writable=True),
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
    click.echo(geometry)
    click.echo(buffer)
    click.echo(directory)
    click.echo(tile_json)
    click.echo(output)
    click.echo(raise_errors)
    click.echo('Initialized the database')


if __name__ == '__main__':
    main()
