### `package_tiles`

**Note**: this is deprecated in favor of Mapbox's [sideloading offline
maps](https://github.com/mapbox/mapbox-gl-native/wiki/Sideloading-offline-maps).

A command line interface to package map tiles into Zip files for given geometries.

Map tiles, especially vector map tiles, are tiny, on the order of a couple dozen
kb. It's a waste of time spent on HTTP pinging to download each of them
individually for offline use, especially when I know ahead of time the areas a
user will download.

So the idea with this is that I create zipped files that contain all the map
tiles for a given section of trail. Then the mobile app downloads that zip file,
the app extracts the tiles, I point Mapbox to the extracted folders, and voilà!
offline maps.

The command takes a geometry, optionally generates a buffer, and copies the map
tiles within that buffer to an output directory. (This command doesn't actually
zip the folder, so that inspection is easy.) The output folder structure is
```
output_dir/{buffer_distance}/{tileset_name}/{z}/{x}/{y}.{png,pbf}
```
with the following definitions:

- `buffer_distance`: distance around geometry in miles, provided as `--buffer` option. If
  multiple buffers are provided, tiles will be created as the difference between
  the current buffer distance and the previous one. I.e. if you pass `--buffer
  "2 5 10"`, the `5` directory will hold the tiles that are in the 5-mile buffer
  but outside the 2-mile buffer. If you don't want this nesting, just run the
  command multiple times, each time specifying a single buffer value.
- `tileset_name`: this name is derived from the last name of the provided
  directory path. So if the directory path is `path/to/dir`, the tileset name
  will be set to `dir`
- `z`, `x`, `y`: this corresponds to the coordinate of the tile in either XYZ or
  TMS coordinates. This command does not convert TMS tiles to XYZ. If the tile
  source is in TMS, the destination source will be as well.
- `png`, `pbf`: the extension of the output tiles is the same as the source tiles.

#### API

```
> python main.py package-tiles --help
Usage: main.py package-tiles [OPTIONS]

  Package tiles into directory based on distance from trail

  Example: python main.py package-tiles -g
  ../data/pct/polygon/bound/town/ca/acton.geojson -b "0 1 2" -d ~/Desktop -o
  out/

Options:
  -g, --geometry FILE        Geometries to use for packaging tiles. Can be any
                             format readable by GeoPandas.  [required]
  -b, --buffer TEXT          Buffer distance (in miles) to use around provided
                             geometries. If you want multiple buffer
                             distances, pass as --buffer "2 5 10"  [required]
  -d, --directory DIRECTORY  Directory root of tiles to package. If multiple
                             options are provided, will package each of them.
                             [required]
  -t, --tile-json FILE       Paths to tile.json files for each directory. If
                             not provided, assumes a tile JSON file is at
                             directory/tile.json. Otherwise, the same number
                             of options as directory must be provided.
  -z, --min-zoom INTEGER     Min zoom for each tile source
  -Z, --max-zoom INTEGER     Max zoom for each tile source
  -o, --output PATH          Output directory  [required]
  --raise / --no-raise       Whether to raise an error if a desired tile is
                             not found in the directory.
  -v, --verbose              Verbose output
  --help                     Show this message and exit.
```

#### Example

Here, the first source tile pair links to a directory with OpenMapTiles tiles,
and copies a maximum of zoom 14 (inclusive). The next copies Terrain RGB png
files up to zoom 12 (inclusive); the last copies contours up to zoom 11
(inclusive). The tiles are copy to `output_dir/` (relative to the current
directory). `--no-raise` tells it not to raise an error if a requested tile does
not exist. For example, I didn't download/generate OpenMapTiles for Mexico or
Canada, so part of the buffer for the start and end of the trail might be
missing.

```
python main.py package-tiles \
    --geometry ../data/pct/line/halfmile/CA_Sec_A_tracks.geojson \
    --buffer "2 5 10" \
    -d ../../openmaptiles/ca_or_wa \
    -Z 14 \
    -d ../../hillshade/data/terrain_png \
    -Z 12 \
    -d ../../contours/contours \
    -Z 11 \
    -o output_dir/ \
    --no-raise \
    --verbose
```
