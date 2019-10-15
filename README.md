
### OpenStreetMap

1. Download extracts from Geofabrik. PBF is fine. E.g.

    - Southern California: http://download.geofabrik.de/north-america/us/california/socal.html
    - Northern California: http://download.geofabrik.de/north-america/us/california/norcal.html
    - Oregon: http://download.geofabrik.de/north-america/us/oregon.html
    - Washington: http://download.geofabrik.de/north-america/us/washington.html
2. Use `osmconvert` to get an extract. Use `--out-o5m` because `osmfilter` in the next step can only read `.o5m` or `.osm` and the former has much smaller file sizes and is faster to read. Use `-b` to use a bounding box, or `-B` to supply a polygon. I.e.:

    ```
    osmconvert washington-latest.pbf --out-o5m -b=-122.231441,45.455465,-119.792476,49.040709 > washington.o5m
    osmconvert socal-latest.osm.pbf --out-o5m -b=-116.951373,32.524291,-115.858233,33.998650 > socal.o5m
    ```

3. Use `osmfilter` to get areas of interest.

    ```
    osmfilter socal.o5m  --keep-relations="@id=1225378" --keep-ways= --keep-nodes= -o=pct-socal.osm
    ```

osmconvert washington-latest.osm --out-o5m -b=-122.231441,45.455465,-119.792476,49.040709 > washington.o5m
