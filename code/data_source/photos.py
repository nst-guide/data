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

        It appears that my photos are uniformly 1 hour behind the accurate time.
        For some reason, my photos are listed as having UTC-6, when Pacific
        Daylight Time is UTC-7.

        Since offsets from UTC are confusing, here's an example: If I took a
        photo at 10:00AM set to UTC-6, the timestamp would be 16:00Z. In UTC-7,
        that would be 9:00AM. Since the actual time was 10AM in UTC-7, I need to
        add one hour so that the UTC time is correct.

        Still a little confusing to me, but my manual checks confirmed that
        adding 1 hour gave accurate geocoding at both the start and end of the
        trail.

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
                'desc': photo.description
            }
            date = pd.to_datetime(photo.date, utc=True) + pd.DateOffset(hours=1)
            d['date'] = date.isoformat()
            properties.append(d)

            path = photo.path_edited if photo.path_edited is not None else photo.path
            uuid_xw[path] = photo.uuid

        features = []
        for g, prop in zip(geometries, properties):
            features.append(geojson.Feature(geometry=g, properties=prop))

        fc = geojson.FeatureCollection(features)
        return fc, uuid_xw

    def _geotag_photo(self, photo, points):
        """Geotag single photo

        Args:
            - photo: osxphotos.PhotoInfo instance
            - points: GeoDataFrame of watch GPS points with timestamps

        Returns:
            - shapely.geometry.Point
        """
        # Convert photo's date to a pandas Timestamp object in UTC
        dt = pd.to_datetime(photo.date, utc=True)
        # Fix timestamp by adding 1 hour
        dt += pd.DateOffset(hours=1)

        # Find closest point previous in time
        idx = points.index.get_loc(dt, method='pad')
        # Get the two nearest rows
        rows = points.iloc[idx:idx + 2]

        # Linearly interpolate between the two rows' timestamps and the
        # photo's timestamp
        # Difference in time b
        a = rows.index[0].tz_convert(None)
        b = rows.index[1].tz_convert(None)
        c = dt.tz_convert(None)
        # Percentage of the way from a to b
        pct = (c - a) / (b - a)
        # Line between the two points
        line = LineString([rows.iloc[0].geometry, rows.iloc[1].geometry])
        # Find interpolated point
        interp = line.interpolate(pct, normalized=True)

        return interp

    def find_photos(self, album='nst-guide-web'):
        """Recursively find photos that were taken between dates

        Args:
            - album: name of album

        Returns:
            List of osxphotos.PhotoInfo
        """
        photosdb = osxphotos.PhotosDB()
        assert album in photosdb.albums, f'Album {album} not found'
        photos = photosdb.photos(albums=[album])
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
