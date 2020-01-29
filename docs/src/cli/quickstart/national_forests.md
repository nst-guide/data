# National Forests layer

Properties:

- `forestname`: Name of forest from source USFS GIS dataset
- `gis_acres`: # of acres of forest from source USFS GIS dataset
- `geometry`: Polygon/MultiPolygon geometry of forest from source USFS GIS
  dataset. Only polygons that intersect the trail of interest are included, but
  some national forests, like Inyo National Forest, are quite wide-ranging, so
  geometries are kept in Nevada I think because it has the same name.
- `length`: length of trail in national forest in meters
- `wiki_image`: url to Wikipedia image. I try to select the best image but it
  can be difficult sometimes.
- `wiki_url`: url to wikipedia page
- `wiki_summary`: summary of wikipedia page. Usually this is the first paragraph.
- `official_url`: url to National Forest homepage

```bash
# Make temp directory
mkdir -p tmp
python code/main.py export national-forests \
    `# trail code, i.e. 'pct'` \
    -t pct > tmp/nationalforests.geojson
```

Run tippecanoe on the GeoJSON to create vector tiles
```bash
rm -rf tmp/nationalforests_tiles
tippecanoe \
    `# Guess appropriate max zoom` \
    -zg \
    `# Layer name` \
    -l nationalforests \
    `# Export tiles to directory` \
    -e tmp/nationalforests_tiles \
    `# Input geojson` \
    tmp/nationalforests.geojson
```

Convert the exported metadata.json to a JSON file conforming to the Tile JSON
spec
```bash
python code/main.py util metadata-json-to-tile-json \
    `# Set tileset name` \
    --name 'National Forests' \
    `# Set attribution string` \
    --attribution '<a href="https://www.nps.gov/" target="_blank">© USFS</a>' \
    `# tile url paths` \
    --url 'https://tiles.nst.guide/pct/nationalforest/{z}/{x}/{y}.pbf' \
    `# Output file path` \
    -o tmp/nationalforests.json \
    `# input JSON file` \
    tmp/nationalforests_tiles/metadata.json
```

Remove the unneeded `metadata.json`
```bash
rm tmp/nationalforests_tiles/metadata.json
```

Remove existing vector tiles
```bash
aws s3 rm \
    --recursive \
    s3://tiles.nst.guide/pct/nationalforest/
```

Add new vector tiles
```bash
aws s3 cp \
    tmp/nationalforests_tiles s3://tiles.nst.guide/pct/nationalforest/ \
    --recursive \
    --content-type application/x-protobuf \
    --content-encoding gzip \
    `# Set to public read access` \
    --acl public-read \
    `# one day cache; one week swr` \
    --cache-control "public, max-age=86400, stale-while-revalidate=604800"
aws s3 cp \
    tmp/nationalforests.json s3://tiles.nst.guide/pct/nationalforest/tile.json \
    `# Set to public read access` \
    --acl public-read \
    --content-type application/geo+json
```
