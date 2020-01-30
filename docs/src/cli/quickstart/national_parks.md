# National Parks layer

Properties:

- `description`: NPS description of park. A couple sentences
- `directionsInfo`: NPS directions to park.
- `directionsUrl`: URL to NPS website for more info on directions
- `fullName`: full name of park, i.e. "Devils Postpile National Monument"
- `length`: length in meters of PCT in park
- `url`: URL to NPS webpage for park
- `weatherInfo`: NPS weather info

```bash
# Make temp directory
mkdir -p tmp
# Generate national park polygons
python code/main.py export national-parks \
    `# trail code, i.e. 'pct'` \
    -t pct > tmp/nationalparks.geojson
# Generate national park labels
python code/main.py geom polylabel \
    `# include only the name attribute` \
    -y fullName \
    `# only keep labels for polygons that are >=30% of MultiPolygon area` \
    --rank-filter 0.2 \
    tmp/nationalparks.geojson > tmp/nationalparks_label.geojson
```

Run tippecanoe on the GeoJSON to create vector tiles
```bash
rm -rf tmp/nationalparks_tiles
tippecanoe \
    `# Guess appropriate max zoom` \
    -zg \
    `# Export tiles to directory` \
    -e tmp/nationalparks_tiles \
    `# Input geojson` \
    -L'{"file":"tmp/nationalparks.geojson", "layer":"nationalparks"}' \
    -L'{"file":"tmp/nationalparks_label.geojson", "layer":"nationalparks_label"}'
```

Convert the exported metadata.json to a JSON file conforming to the Tile JSON
spec
```bash
python code/main.py util metadata-json-to-tile-json \
    `# Set tileset name` \
    --name 'National Parks' \
    `# Set attribution string` \
    --attribution '<a href="https://www.nps.gov/" target="_blank">© NPS</a>' \
    `# tile url paths` \
    --url 'https://tiles.nst.guide/nationalpark/{z}/{x}/{y}.pbf' \
    `# Output file path` \
    -o tmp/nationalparks.json \
    `# input JSON file` \
    tmp/nationalparks_tiles/metadata.json
# Remove the unneeded `metadata.json`
rm tmp/nationalparks_tiles/metadata.json
```

Remove existing vector tiles
```bash
aws s3 rm \
    --recursive \
    s3://tiles.nst.guide/nationalpark/
```

Add new vector tiles
```bash
aws s3 cp \
    tmp/nationalparks_tiles s3://tiles.nst.guide/nationalpark/ \
    --recursive \
    --content-type application/x-protobuf \
    --content-encoding gzip \
    `# Set to public read access` \
    --acl public-read \
    `# two hour cache; one day swr` \
    --cache-control "public, max-age=7200, stale-while-revalidate=86400"
aws s3 cp \
    tmp/nationalparks.json s3://tiles.nst.guide/nationalpark/tile.json \
    `# Set to public read access` \
    --acl public-read \
    --content-type application/json
```
