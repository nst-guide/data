import json
from datetime import datetime
from pathlib import Path
from subprocess import run
from typing import List, Union

import geopandas as gpd
import osxphotos
import pandas as pd
import pytz
from dateutil.parser import parse
from shapely.geometry import LineString


class PhotosLibrary:
    """Geotag photos from hike

    I have two sets of photos; photos from my phone, an iPhone XR, and from my
    camera, a Sony a6000. Photos taken by my iPhone are automatically stored in
    HEIC format, a private format developed by Apple.
    """
    def __init__(self):
        super(PhotosLibrary, self).__init__()
        self.photos_dir = Path('~/Pictures').expanduser()

    def geotag_photos(self, photos, points):
        """Geotag photos

        Args:
            - photos: list of osxphotos.PhotoInfo instances
            - points: DataFrame of points from watch

        Returns:
            - GeoJSON FeatureCollection of points representing photo locations
              and metadata for each photo:
                - uuid: UUID from Photos.app for photo
                - favorite: True if photo is listed as a favorite in Photos.app
                - keywords: list of keywords from Photos.app
                - title: title from Photos.app
                - desc: description from Photos.app
                - date: corrected photo date in ISO8601 format
                - path: path to edited photo if it exists, otherwise to original
                  photo

            - dict linking file paths to UUIDs from Photos.app
        """
        # Fix dates
        photos['date'] = photos.apply(
            lambda row: self._get_photo_date(row), axis=1)

        # Geotag points and convert to GeoDataFrame
        photos = gpd.GeoDataFrame(
            photos,
            geometry=photos.apply(
                lambda photo: self._geotag_photo(photo, points), axis=1))

        return photos

    def _get_photo_date(self, photo):
        """Get Timestamp for photo

        It looks like I need to add one hour to most photos, unless they already
        come in as UTC-7. Most photos from my a6000 come in as UTC-6, which is
        one hour behind. But for example, any photo that I transferred by wifi
        from the camera to my phone is stored in Photos.app with the correct
        time as UTC-7.

        In general, my a6000 photos are uniformly 1 hour behind the accurate
        time. For some reason, my photos are listed as having UTC-6, when
        Pacific Daylight Time is UTC-7.

        Since offsets from UTC are confusing, here's an example: If I took a
        photo at 10:00AM set to UTC-6, the timestamp would be 16:00Z. In UTC-7,
        that would be 9:00AM. Since the actual time was 10AM in UTC-7, I need to
        add one hour so that the UTC time is correct.

        Still a little confusing to me, but my manual checks confirmed that
        adding 1 hour gave accurate geocoding at both the start and end of the
        trail.

        Args:
            - photo: pandas Series

        Returns:
            pd.Timestamp in UTC (timezone naive)
        """
        # Convert photo's date to a pandas Timestamp object
        dt = pd.to_datetime(photo.date)

        # If the time zone is UTC-6, I need to add an hour
        if dt.utcoffset().total_seconds() / 60 / 60 == -6:
            dt += pd.DateOffset(hours=1)
        # If the time zone is already UTC-7, it should be good
        elif dt.utcoffset().total_seconds() / 60 / 60 == -7:
            pass
        else:
            msg = f'tz not UTC-6 or UTC-7: {dt.tz}'
            raise ValueError(msg)

        # Convert to UTC
        dt = dt.tz_convert(None)
        return dt

    def _geotag_photo(self, photo, points):
        """Geotag single photo

        Args:
            - photo: pandas Series
            - points: GeoDataFrame of watch GPS points with timestamps

        Returns:
            - shapely.geometry.Point
        """
        dt = photo.date

        # Find closest point previous in time
        idx = points.index.get_loc(dt, method='pad')
        # Get the two nearest rows
        rows = points.iloc[idx:idx + 2]

        # Linearly interpolate between the two rows' timestamps and the
        # photo's timestamp
        # Difference in time b
        a = rows.index[0].tz_convert(None)
        b = rows.index[1].tz_convert(None)
        # Percentage of the way from a to b
        pct = (dt - a) / (b - a)
        # Line between the two points
        line = LineString([rows.iloc[0].geometry, rows.iloc[1].geometry])
        # Find interpolated point
        interp = line.interpolate(pct, normalized=True)

        return interp

    def find_photos(
            self, albums=None, start_date=None, end_date=None, exif=False):
        """Recursively find photos that were taken between dates

        Args:

            - album: name of album
            - start_date: first day to include photos
            - end_date: last day to include photos
            - exif: if True, joins with metadata from exiftool

        Returns:
            List of osxphotos.PhotoInfo
        """
        photosdb = osxphotos.PhotosDB()
        args = {}
        if albums is not None:
            msg = f'Album not found'
            assert all(album in photosdb.albums for album in albums), msg
            args['albums'] = albums

        # Find photos
        photos = photosdb.photos(**args)

        tz = pytz.timezone('America/Los_Angeles')
        if start_date is not None:
            if not isinstance(start_date, datetime):
                start_date = parse(start_date)

            # Assign tz
            start_date = tz.localize(start_date)

        if end_date is not None:
            if not isinstance(end_date, datetime):
                end_date = parse(end_date)

            # Assign tz
            end_date = tz.localize(end_date)

        # Select photos between dates
        if start_date is not None:
            photos = [photo for photo in photos if photo.date >= start_date]

        if end_date is not None:
            photos = [photo for photo in photos if photo.date <= end_date]

        # Turn photos into pandas DataFrame
        # Currently there's a bug in osxphotos and one photo gives an error
        data = []
        for p in photos:
            try:
                data.append(json.loads(p.json()))
            except NameError:
                continue
        photos = pd.DataFrame.from_records(data)

        if exif:
            meta = self.get_photos_metadata()
            meta = pd.DataFrame.from_records(meta)

            # Rename FileName to filename so that merge works
            meta = meta.rename(columns={'FileName': 'filename'})

            # Merge photos with EXIF metadata from exiftool
            photos = pd.merge(photos, meta, on='filename', indicator=True)

            msg = 'Some photos not merged with EXIF metadata'
            assert photos['_merge'].value_counts()['left_only'] == 0, msg

        return photos

    def get_photos_metadata(self, overwrite=False):
        """Get EXIF data from photos library using Exiftool
        """
        metadata_path = self.photos_dir / 'metadata.json'
        if overwrite or (not metadata_path.exists()):
            self._run_exiftool_metadata()

        # Load metadata
        with open(metadata_path) as f:
            metadata = json.load(f)

        return metadata

    def _run_exiftool_metadata(self):
        """
        Deprecated: used with exiftool but osxphotos seems to be good enough for
        my needs
        """
        cmd = 'exiftool -n -j -r Photos\ Library.photoslibrary/originals > metadata.json'
        run(cmd, check=True, shell=True, cwd=self.photos_dir)

    def get_metadata_for_folder(folder: Union[str, Path], ext='.HEIC'):
        """Recursively get metadata for all images within folder
        """
        # If string, remove trailing /
        if isinstance(folder, str):
            folder = folder.rstrip('/')

        recurse_dir = f'"{str(folder)}/"'
        cmd = ['exiftool', '-j', recurse_dir]
        # -j json output
        # -r recurse directory
        # -n Prevent pretty print formatting. Also gives lat/lon GPS coords
        cmd = f'exiftool -j -r -n -ext {ext} {recurse_dir}'

        res = run(cmd, shell=True, capture_output=True)
        json.loads(res.stdout)

    def get_metadata_for_files(paths: List[Union[str, Path]]):
        cmd = ['exiftool', '-j', '-n', *[str(x) for x in paths]]
        res = run(cmd, capture_output=True)
        return json.loads(res.stdout)
