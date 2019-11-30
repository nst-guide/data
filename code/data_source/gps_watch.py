from subprocess import run

import geojson
import geopandas as gpd
import gpxpy
import gpxpy.gpx

from .base import DataSource


class GPSTracks(DataSource):
    def __init__(self):
        super(GPSTracks, self).__init__()
        self.raw_dir = self.data_dir / 'raw' / 'tracks'

    def convert_fit(self):
        """
        The raw files of these GPS tracks are stored in the Git repository, but
        they still need to be converted into a helpful format.

        There doesn't appear to be a great Python package to work with .fit
        files, so I'm using [GPSBabel][gpsbabel] to do the conversion.

        [gpsbabel]: https://www.gpsbabel.org
        """

        gpsbabel_path = '/Applications/GPSBabelFE.app/Contents/MacOS/gpsbabel'

        for fit_file in self.raw_dir.glob('*.fit'):
            geojson_path = fit_file.parents[0] / (fit_file.stem + '.geojson')
            cmd = [
                gpsbabel_path, '-i', 'garmin_fit', '-f',
                str(fit_file), '-o', 'geojson', '-F',
                str(geojson_path)
            ]
            run(cmd, check=True)

            gpx_path = fit_file.parents[0] / (fit_file.stem + '.gpx')
            cmd = [
                gpsbabel_path, '-i', 'garmin_fit', '-f',
                str(fit_file), '-o', 'gpx', '-F',
                str(gpx_path)
            ]
            run(cmd, check=True)

        # Now join all of these together
        features = []
        for geojson_file in self.raw_dir.glob('*.geojson'):
            with open(geojson_file) as f:
                d = geojson.load(f)

            features.extend(d['features'])

        fc = geojson.FeatureCollection(features)
        save_dir = self.data_dir / 'pct' / 'line' / 'gps_track'
        save_dir.mkdir(exist_ok=True, parents=True)
        with open(save_dir / 'gps_track.geojson', 'w') as f:
            geojson.dump(fc, f)

    def trail(self):
        gdf = gpd.read_file(
            self.data_dir / 'pct' / 'line' / 'gps_track' / 'gps_track.geojson')
        return gdf

    def load_tracks(self):
        """Load saved GPX tracks

        Returns:
            Iterable of gpxpy track objects
        """
        for gpx_file in self.raw_dir.glob('*.gpx'):
            with gpx_file.open() as f:
                gpx = gpxpy.parse(f)

                assert len(gpx.tracks) == 1, f'>1 track in GPX file: {gpx_file}'
                track = gpx.tracks[0]

                yield track

    def project_onto_line(self, gdf):
        tracks = self.load_tracks()
