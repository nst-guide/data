# Wilderness layer

Properties:

- `url`: url to wilderness.net page for the wilderness
- `name`: full name for wilderness
- `acreage`: # of acres in wilderness
- `descriptio`: Wilderness.net description. Note that this is cut off; after a
  given number of characters it just has `...`.
- `agency`: the agency that runs the wilderness. For the PCT dataset it appears
  only values of `NPS`, `FS`, and `BLM` exist.
- `yeardesign`: year the area was federally designated as wilderness
- `geometry`: Polygon/MultiPolygon of wilderness area
- `length`: Length of trail inside park (in meters)
- `wiki_image`: url to Wikipedia image. I try to select the best image but it
  can be difficult sometimes.
- `wiki_url`: url to wikipedia page
- `wiki_summary`: summary of wikipedia page. Usually this is the first paragraph.

```bash
# Make temp directory
mkdir -p tmp
# Generate polygons
python code/main.py export wilderness \
    `# trail code, i.e. 'pct'` \
    -t pct > tmp/wilderness.geojson
# Generate labels
python code/main.py geom polylabel \
    `# include only the name attribute` \
    -y name \
    `# only keep labels for polygons that are >=30% of MultiPolygon area` \
    --rank-filter 0.2 \
    tmp/wilderness.geojson > tmp/wilderness_label.geojson
```

Run tippecanoe on the GeoJSON to create vector tiles
```bash
rm -rf tmp/wilderness_tiles
tippecanoe \
    `# Guess appropriate max zoom` \
    -zg \
    `# Export tiles to directory` \
    -e tmp/wilderness_tiles \
    `# Input geojson` \
    -L'{"file":"tmp/wilderness.geojson", "layer":"wilderness"}' \
    -L'{"file":"tmp/wilderness_label.geojson", "layer":"wilderness_label"}'
```

Convert the exported metadata.json to a JSON file conforming to the Tile JSON
spec
```bash
python code/main.py util metadata-json-to-tile-json \
    `# Set tileset name` \
    --name 'Designated Wilderness' \
    `# Set attribution string` \
    --attribution '<a href="https://www.wilderness.net/" target="_blank">© Wilderness.net</a>' \
    `# tile url paths` \
    --url 'https://tiles.nst.guide/pct/wilderness/{z}/{x}/{y}.pbf' \
    `# Output file path` \
    -o tmp/wilderness.json \
    `# input JSON file` \
    tmp/wilderness_tiles/metadata.json
# Remove the unneeded `metadata.json`
rm tmp/wilderness_tiles/metadata.json
```

Remove existing vector tiles
```bash
aws s3 rm \
    --recursive \
    s3://tiles.nst.guide/pct/wilderness/
```

Add new vector tiles
```bash
aws s3 cp \
    tmp/wilderness_tiles s3://tiles.nst.guide/pct/wilderness/ \
    --recursive \
    --content-type application/x-protobuf \
    --content-encoding gzip \
    `# Set to public read access` \
    --acl public-read \
    `# two hour cache; one day swr` \
    --cache-control "public, max-age=7200, stale-while-revalidate=86400"
aws s3 cp \
    tmp/wilderness.json s3://tiles.nst.guide/pct/wilderness/tile.json \
    `# Set to public read access` \
    --acl public-read \
    --content-type application/json
```
