# National Parks layer

Properties:

cols = [
    'year', 'name', 'acres', 'inciwebid', 'geometry', 'length',
    'wiki_image', 'wiki_url', 'wiki_summary'
]

- `year`: Year of wildfire
- `name`: Common name of wildfire, e.g. "Norse Peak"
- `acres`: Last-updated acres of wildfire
- `inciwebid`: ID of inciweb page. Can be used to link to inciweb
- `geometry`: Polygon/MultiPolygon of wildfire perimeters
- `length`: length in meters of PCT in wildfire perimeter. Does not count alternates.

Not all fires have Wikipedia pages, but for some objects they have these
properties:

- `wiki_image`: Best image in wikipedia
- `wiki_url`: URL to wikipedia page
- `wiki_summary`: Summary from wikipedia page

```bash
# Make temp directory
mkdir -p tmp
# Generate polygons
python code/main.py export wildfire-historical \
    `# trail code, i.e. 'pct'` \
    -t pct > tmp/wildfire_historical.geojson
# generate labels
python code/main.py geom polylabel \
    `# include only the name attribute` \
    -y name \
    `# only keep labels for polygons that are >=30% of MultiPolygon area` \
    --rank-filter 0.2 \
    tmp/wildfire_historical.geojson > tmp/wildfire_historical_label.geojson
```

Run tippecanoe on the GeoJSON to create vector tiles
```bash
rm -rf tmp/wildfire_historical_tiles
tippecanoe \
    `# Guess appropriate max zoom` \
    -zg \
    `# Export tiles to directory` \
    -e tmp/wildfire_historical_tiles \
    `# Input geojson` \
    -L'{"file":"tmp/wildfire_historical.geojson", "layer":"wildfire_historical"}' \
    -L'{"file":"tmp/wildfire_historical_label.geojson", "layer":"wildfire_historical_label"}'
```

Convert the exported metadata.json to a JSON file conforming to the Tile JSON
spec
```bash
python code/main.py util metadata-json-to-tile-json \
    `# Set tileset name` \
    --name 'Historical Wildfires' \
    `# Set attribution string` \
    --attribution '<a href="https://www.nifc.gov/" target="_blank">© NIFC</a>' \
    `# tile url paths` \
    --url 'https://tiles.nst.guide/pct/wildfire_historical/{z}/{x}/{y}.pbf' \
    `# Output file path` \
    -o tmp/wildfire_historical.json \
    `# input JSON file` \
    tmp/wildfire_historical_tiles/metadata.json
# remove unneeded metadata.json
rm tmp/wildfire_historical_tiles/metadata.json
```

Remove existing vector tiles
```bash
aws s3 rm \
    --recursive \
    s3://tiles.nst.guide/pct/wildfire_historical/
```

Add new vector tiles
```bash
aws s3 cp \
    tmp/wildfire_historical_tiles s3://tiles.nst.guide/pct/wildfire_historical/ \
    --recursive \
    --content-type application/x-protobuf \
    --content-encoding gzip \
    `# Set to public read access` \
    --acl public-read \
    `# two hour cache; one day swr` \
    --cache-control "public, max-age=7200, stale-while-revalidate=86400"
aws s3 cp \
    tmp/wildfire_historical.json s3://tiles.nst.guide/pct/wildfire_historical/tile.json \
    `# Set to public read access` \
    --acl public-read \
    --content-type application/json
```
