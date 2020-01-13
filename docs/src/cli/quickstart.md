# Quickstart

This doc has overviews of the available CLI commands. For full options, check
the API for each command, which is also available by appending `--help` to the
command.

## Tiles

### Uploading newer versions of tiles near the PCT to AWS

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
    > tiles=$(cat tiles_ca_south.txt | \
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

    Then copy the tiles that exist into a new directory:

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

    ```bash
    aws s3 cp \
        $new_dir s3://tiles.nst.guide/openmaptiles/ \
        --recursive \
        --content-type application/x-protobuf \
        --content-encoding gzip \
        --cache-control "public, max-age=2592000, stale-while-revalidate=31536000"
    ```
