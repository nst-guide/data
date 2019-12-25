from subprocess import run

import geojson
import geopandas as gpd
import gpxpy
import gpxpy.gpx
import pandas as pd

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

    def points_df(self):
        """Load GPX track points into Pandas DataFrame

        GeoJSON files don't store other helpful information like time or
        altitude, which are stored in a GPX file. This creates a pandas
        DataFrame mapping timestamps to gps locations. This allows for creating
        an ordered list of timestamps that's possible to be interpolated
        between.

        GPX files can have one or more _tracks_, one or more _segments_ within
        each track, and one or more _points_ within each segment.

        All track points should have a latitude, longitude, and timestamp. Some,
        but not all, track points also have an elevation.

        Returns:
            DataFrame with columns
            - time: tz aware column of timestamps
            - ele: elevation in m; often missing
            - lat: latitude
            - lon: longitude
        """
        points = []
        for gpx_file in self.raw_dir.glob('Move_*.gpx'):
            with gpx_file.open() as f:
                gpx = gpxpy.parse(f)

                for track in gpx.tracks:
                    for segment in track.segments:
                        for point in segment.points:
                            points.append(point)

        rows = [{
            'time': p.time,
            'ele': p.elevation,
            'lat': p.latitude,
            'lon': p.longitude
        } for p in points]
        df = pd.DataFrame.from_records(rows)

        # Sort df on timestamp
        df = df.sort_values('time')

        # Coerce lat/lon columns to GeoDataFrame geometry
        df = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df['lon'], df['lat']),
            crs={'init': 'epsg:4326'})
        df = df.drop(['lat', 'lon'], axis=1)

        # Set timestamp as index
        df = df.set_index('time')
        return df
