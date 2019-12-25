import json
from pathlib import Path
from subprocess import run
from typing import List, Union

import geojson
import osxphotos
import pandas as pd
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
        geometries = []
        properties = []
        uuid_xw = {}
        for photo in photos:
            point = self._geotag_photo(photo, points)
            geometries.append(point)

            d = {
                'uuid': photo.uuid,
                'favorite': photo.favorite,
                'keywords': photo.keywords,
                'title': photo.title,
                'desc': photo.description,
                'date': self._get_photo_date(photo).isoformat()
            }
            properties.append(d)

            path = photo.path_edited if photo.path_edited is not None else photo.path
            uuid_xw[path] = photo.uuid

        features = []
        for g, prop in zip(geometries, properties):
            features.append(geojson.Feature(geometry=g, properties=prop))

        fc = geojson.FeatureCollection(features)
        return fc, uuid_xw

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
            - photo: osxphotos.PhotoInfo instance

        Returns:
            pd.Timestamp in UTC (timezone naive)
        """
        # Convert photo's date to a pandas Timestamp object
        dt = pd.to_datetime(photo.date)

        tzname = dt.tz.tzname(None)
        # If the time zone is UTC-6, I need to add an hour
        if tzname == 'UTC-06:00':
            dt += pd.DateOffset(hours=1)
        # If the time zone is already UTC-7, it should be good
        elif tzname == 'UTC-07:00':
            pass
        else:
            msg = f'tz not UTC-6 or UTC-7: {tzname}'
            raise ValueError(msg)

        # Convert to UTC
        dt = dt.tz_convert(None)
        return dt

    def _geotag_photo(self, photo, points):
        """Geotag single photo

        Args:
            - photo: osxphotos.PhotoInfo instance
            - points: GeoDataFrame of watch GPS points with timestamps

        Returns:
            - shapely.geometry.Point
        """
        dt = self._get_photo_date(photo)

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

    def find_photos(self, albums=None):
        """Recursively find photos that were taken between dates

        Args:
            - album: name of album

        Returns:
            List of osxphotos.PhotoInfo
        """
        photosdb = osxphotos.PhotosDB()
        args = {}
        if albums is not None:
            msg = f'Album not found'
            assert all(album in photosdb.albums for album in albums), msg
            args['albums'] = albums
        photos = photosdb.photos(**args)
        return photos

    def get_photos_metadata(self, overwrite=False):
        """
        Deprecated: used with exiftool but osxphotos seems to be good enough for
        my needs
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
        res.stderr
