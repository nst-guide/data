import click


@click.group()
def main():
    pass

@main.command()
def initdb():
    click.echo('Initialized the database')

@main.command()
def dropdb():
    click.echo('Dropped the database')


if __name__ == '__main__':
    main()
