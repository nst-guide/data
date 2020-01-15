# Quickstart

This doc has overviews of the available CLI commands. For full options, check
the API for each command, which is also available by appending `--help` to the
command.


## Tiles

### Uploading newer versions of tiles near the PCT to AWS

Since I'm trying to have an app for the PCT specifically, I care about having
updated OpenStreetMap data near the PCT, but further away from the trail and
from trail towns is not as important. It's simple to update tiles for any
arbitrary Geofabrik extract region, aka easy to update for the state of
Washington, as I can just run OpenMapTiles for that region. The drawback of
that, however, is that map tiles as a directory are thousands and thousands of
very tiny files, so the PUT requests to AWS S3 actually add up.

For example, for zooms 0-14, the state of Oregon makes up 191306 tiles. Since
it's $0.005 per 1000 put requests, it's just shy of $1 each time I update the
tiles. I calculated that if I were to upload tiles for the entire continental
US, it would likely be just shy of $100 for each set of PUT requests.

The following instructions show how to update tiles for just a given buffer
around the PCT, which is on the order of $0.07 for each upload for each fifth of
the trail.

1. Create new tiles from e.g. the [OpenMapTiles repository](https://github.com/nst-guide/openmaptiles).
2. Export the `.mbtiles` file to a directory of tiles:

    ```bash
    mb-util tiles.mbtiles tiles --image_format=pbf
    ```

3. Get tiles for a section of the PCT, e.g.

    - `-t`: trail code
    - `-s`: trail section (optional)
    - `-z`: min zoom
    - `-Z`: max zoom
    - `-b`: buffer distance in miles around trail

    ```bash
    python code/main.py tiles tiles-for-trail \
        -t pct \
        -s ca_south \
        -z 0 \
        -Z 14 \
        -b 15 > tiles_ca_south.txt
    ```

4. Loop over those tiles and copy them to a new directory

    It's _really_ slow to run `aws s3 cp` a new time for each file, and much
    much faster to run `aws s3 cp --recursive` on a directory, so the best
    approach is to copy the desired tiles into a new directory, then `aws s3 cp`
    that directory to AWS.

    Remove the `[`, `,`, and `]` characters, and reorder `x,y,z` to `z,x,y`:

    ```bash
    fname="tiles_ca_south.txt"
    # Make sure to update .pbf to .png if you're working with non-vector tiles
    tiles=$(cat $fname | \
        tr -d '[,]' | \
        awk '{print $3 "/" $1 "/" $2 ".pbf"}')
    ```

    Outputs:

    ```
    > echo $tiles
    ...
    14/6632/2892.pbf
    14/6632/2893.pbf
    14/6632/2894.pbf
    14/6632/2895.pbf
    14/6632/2896.pbf
    ...
    ```

    Then copy the tiles that exist into a new directory (note, you could
    probably make this faster by skipping the `if $tile` check, since `cp` will
    just print an error but not stop the loop. However, this might create empty
    directories if `$tile` doesn't actually exist.):

    ```bash
    new_dir="../tiles_tmp"
    echo $tiles | while read tile; do
        if [ -f $tile ]; then
            echo "$tile";
            mkdir -p $new_dir/$(dirname $tile)
            cp $tile $new_dir/$tile
        fi
    done
    ```

5. Upload to S3

    Apply one-week caching plus one-year stale while revalidate.

    ```bash
    aws s3 cp \
        $new_dir s3://tiles.nst.guide/openmaptiles/ \
        --recursive \
        --content-type application/x-protobuf \
        --content-encoding gzip \
        --cache-control "public, max-age=604800, stale-while-revalidate=31536000"
    ```
