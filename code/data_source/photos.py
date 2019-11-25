import json
from datetime import datetime
from dateutil import parser
from pathlib import Path
from subprocess import run
from typing import List, Union

self = PhotosLibrary()
class PhotosLibrary:
    """Geotag photos from hike

    I have two sets of photos; photos from my phone, an iPhone XR, and from my
    camera, a Sony a6000. Photos taken by my iPhone are automatically stored in
    HEIC format, a private format developed by Apple.

    The `exiftool` command line tool is able to read the EXIF from virtually any
    file type, including HEIC, so I'll run `exiftool` on the Photos directory,
    then use the output to geotag photos.
    """
    def __init__(self):
        super(PhotosLibrary, self).__init__()

        s = '~/Pictures/Photos Library.photoslibrary/Masters'
        self.photos_dir = Path(s).expanduser()

    def find_photos(self, start_date='2019-04-22', end_date='2019-10-03'):
        """Recursively find photos that were taken between dates

        Args:
            start_date
            end_date
        """
        start_date = parser.parse(start_date)
        end_date = parser.parse(end_date)

        years = range(start_date.year, end_date.year + 1)

        recurse_dir = self.photos_dir / '2019'
        # years =
        self.photos_dir

        f = '/Users/kyle/IMG_1208.HEIC'
        paths = ['/Users/kyle/IMG_0162.HEIC']
        folder = Path('/Users/kyle/tmp/')
        str(folder)


    def get_metadata_for_folder(folder: Union[str, Path], ext='.HEIC'):
        """Recursively get metadata for all images within folder
        """
        # If string, remove trailing /
        if isinstance(folder, str):
            folder = folder.rstrip('/')

        recurse_dir = f'"{str(folder)}/"'
        cmd = [
            'exiftool', '-j', recurse_dir
        ]
        # -j json output
        # -r recurse directory
        # -n Prevent pretty print formatting. Also gives lat/lon GPS coords
        cmd = f'exiftool -j -r -n -ext {ext} {recurse_dir}'

        res = run(cmd, shell=True, capture_output=True)
        json.loads(res.stdout)

    def get_metadata_for_files(paths: List[Union[str, Path]]):
        cmd = [
            'exiftool',
            '-j',
            '-n',
            *[str(x) for x in paths]
        ]
        res = run(cmd, capture_output=True)
        return json.loads(res.stdout)
        res.stderr





        # /Users/kyle/Pictures/Photos Library.photoslibrary/Masters/2019/09/24/20190924-160208
