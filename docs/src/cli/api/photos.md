
## `geotag_photos`

Geotag photos from Photos.app.

```
> python code/main.py photos geotag-photos --help
Usage: main.py photos geotag-photos [OPTIONS]

  Geotag photos from album using watch's GPS tracks

Options:
  -a, --album TEXT       Photos.app album to use for photos geocoding.
  --exif                 Include metadata from exiftool
  --all-cols             Don't select minimal columns
  -o, --out-path FILE    Output path for photo metadata GeoJSON file [required]
  -s, --start-date TEXT  Start date to find photos
  -e, --end-date TEXT    End date to find photos
  -x, --xw-path FILE     Output path for UUID-photo path crosswalk
  --help                 Show this message and exit.
  ```

### Example

```bash
# Package's entry point
python code/main.py \
    `# photos command` \
    photos \
    `# geotag-photos subcommand` \
    geotag-photos \
    `# Select photos from album named nst-guide-web` \
    -a nst-guide-web \
    `# Output the main JSON file with photo metadata to the path` \
    `# nst-guide-web-photos.geojson` \
    -o nst-guide-web-photos.geojson \
    `# Output filename crosswalk to photos_xw.json` \
    -x photos_xw.json
```

## `copy_using_xw`

```
> python code/main.py photos copy-using-xw --help
Usage: main.py photos copy-using-xw [OPTIONS] FILE

  Copy files to out_dir using JSON crosswalk

  For any non-JPEG files, this calls `sips` (mac-cli) to convert them to
  JPEG.

Options:
  -o, --out-dir FILE  Output directory for copied photos  [required]
  --help              Show this message and exit.
```

```bash
# Package entry point
python code/main.py \
    `# photos command` \
    photos \
    `# copy-using-xw subcommand` \
    copy-using-xw \
    `# Copy photos to directory tmp` \
    -o tmp \
    `# use photos_xw.json for copying photos` \
    photos_xw.json
```
