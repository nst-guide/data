# Transit layer

Properties:

**Stops:**

- `geometry`: location of transit stops (usually `Point`)
- `tags`: metadata taken straight from GTFS feed
- `_trail`: `True` if the stop was generated from the trail buffer pass
- `_town`: `True` if the stop was generated from the town polygon pass
- `_nearby_stop`: `True` if the stop is within the trail or town buffer, and not another stop on a route

**Routes:**

- `geometry`: location of transit routes (usually `LineString` or `MultiLineString`)
- `tags`: metadata taken straight from GTFS feed
- `name`: name of transit route
- `vehicle_type`: type of vehicle used for transit route. Usually `bus`
- `color`: Route color in 6 hexadecimal characters
- `operated_by_name`: Name of operator of route
- `_trail`: `True` if the route was generated from the trail buffer pass
- `_town`: `True` if the route was generated from the town polygon pass

```bash
# Make temp directory
mkdir -p tmp
# Generate transit
python code/main.py export transit \
    `# trail code, i.e. 'pct'` \
    -t pct \
    `# file to write transit routes to` \
    --out-routes tmp/transit_routes.geojson \
    `# file to write transit stops to` \
    --out-stops tmp/transit_stops.geojson
```

Run tippecanoe on the GeoJSON to create vector tiles
```bash
rm -rf tmp/transit_tiles
tippecanoe \
    `# Guess appropriate max zoom` \
    -zg \
    `# Export tiles to directory` \
    -e tmp/transit_tiles \
    `# Input geojson` \
    -L'{"file":"tmp/transit_routes.geojson", "layer":"routes"}' \
    -L'{"file":"tmp/transit_stops.geojson", "layer":"stops"}'
```

Convert the exported metadata.json to a JSON file conforming to the Tile JSON
spec
```bash
python code/main.py util metadata-json-to-tile-json \
    `# Set tileset name` \
    --name 'Transit' \
    `# Set attribution string` \
    --attribution '<a href="https://transit.land/" target="_blank">© Transitland</a>' \
    `# tile url paths` \
    --url 'https://tiles.nst.guide/pct/transit/{z}/{x}/{y}.pbf' \
    `# Output file path` \
    -o tmp/transit.json \
    `# input JSON file` \
    tmp/transit_tiles/metadata.json
# Remove the unneeded `metadata.json`
rm tmp/transit_tiles/metadata.json
```

Remove existing vector tiles
```bash
aws s3 rm \
    --recursive \
    s3://tiles.nst.guide/pct/transit/
```

Add new vector tiles
```bash
aws s3 cp \
    tmp/transit_tiles s3://tiles.nst.guide/pct/transit/ \
    --recursive \
    --content-type application/x-protobuf \
    --content-encoding gzip \
    `# Set to public read access` \
    --acl public-read \
    `# two hour cache; one day swr` \
    --cache-control "public, max-age=7200, stale-while-revalidate=86400"
aws s3 cp \
    tmp/transit.json s3://tiles.nst.guide/pct/transit/tile.json \
    `# Set to public read access` \
    --acl public-read \
    --content-type application/json
```
