# Wikipedia layer

The wikipedia layer is constructed by repeatedly calling Wikipedia's [Geosearch
API](https://www.mediawiki.org/wiki/API:Geosearch). The Geosearch API doesn't
allow providing a polygon geometry; you can only provide a point and a radius.
To work around this, I construct a minimal set of circles of max radius 10km
that fully cover the trail with the provided buffer distance.

The result of `wikipedia-for-trail` is a GeoJSON file where the geometries are
`Point`s, and where the properties have the desired attributes from the `-a`
flag.

```bash
mkdir -p tmp
# Entry point
python code/main.py export wikipedia-for-trail \
    `# select the PCT; at this point the only valid option ` \
    --trail-code pct \
    `# provide buffer distance in miles` \
    --buffer 2 \
    `# Selected attributes` \
    -a images -a summary -a title -a url > tmp/wikipedia.geojson
```

Compress this GeoJSON with brotli compression.
```
brotli -c tmp/wikipedia.geojson > tmp/wikipedia_compressed.geojson
```

Then upload this to S3
```bash
aws s3 cp \
    tmp/wikipedia_compressed.geojson s3://tiles.nst.guide/pct/wikipedia.geojson \
    --content-type application/geo+json \
    --content-encoding br \
    `# Set to public read access` \
    --acl public-read \
    `# one day cache; one week swr` \
    --cache-control "public, max-age=86400, stale-while-revalidate=604800"
```
