import re
from pathlib import Path
from zipfile import ZipFile

import geojson
import geopandas as gpd
import gpxpy
import gpxpy.gpx
import pandas as pd
import requests
from shapely.geometry import LineString, Point

import geom

from .base import DataSource


class Halfmile(DataSource):
    """docstring for Halfmile"""
    def __init__(self):
        super(Halfmile, self).__init__()
        self.line_dir = self.data_dir / 'pct' / 'line' / 'halfmile'
        self.line_dir.mkdir(parents=True, exist_ok=True)
        self.point_dir = self.data_dir / 'pct' / 'point' / 'halfmile'
        self.point_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.data_dir / 'raw' / 'halfmile'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, overwrite=False):
        """Download Halfmile tracks and waypoints
        """
        states = ['ca', 'or', 'wa']
        headers = {
            'User-Agent':
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36',
        }

        # First just download the zip files to the raw directory
        for state in states:
            url = 'https://www.pctmap.net/wp-content/uploads/pct/'
            url += f'{state}_state_gps.zip'

            local_path = self.raw_dir / Path(url).name
            if overwrite or (not local_path.exists()):
                # Use requests instead of urlretrieve because of the need to
                # pass a user-agent
                r = requests.get(url, headers=headers)
                with open(local_path, 'wb') as f:
                    f.write(r.content)

        # Use these cached zip files to extract tracks and waypoints
        for state in states:
            with ZipFile(self.raw_dir / f'{state}_state_gps.zip') as z:
                names = [x for x in z.namelist() if '__MACOSX' not in x]
                trk_names = sorted([x for x in names if 'tracks' in x])
                for trk_name in trk_names:
                    fc = self._parse_track_gpx(z.read(trk_name))
                    path = Path(trk_name).stem + '.geojson'
                    with open(self.line_dir / path, 'w') as f:
                        geojson.dump(fc, f)

                wpt_names = sorted([x for x in names if 'waypoints' in x])
                for wpt_name in wpt_names:
                    fc = self._parse_waypoints_gpx(z.read(wpt_name))
                    path = Path(wpt_name).stem + '.geojson'
                    with open(self.point_dir / path, 'w') as f:
                        geojson.dump(fc, f)

    def _parse_track_gpx(self, b):
        gpx = gpxpy.parse(b.decode('utf-8'))

        name_re = re.compile(r'^((?:CA|OR|WA) Sec [A-Z])(?: - (.+))?$')

        features = []
        for track in gpx.tracks:
            assert len(track.segments) == 1, 'More than 1 segment in GPX track'

            l = LineString([(x.longitude, x.latitude, x.elevation)
                            for x in track.segments[0].points])

            section_name, alt_name = name_re.match(track.name).groups()
            name = alt_name if alt_name else section_name
            alternate = bool(alt_name)
            properties = {'name': name, 'alternate': alternate}
            features.append(geojson.Feature(geometry=l, properties=properties))

        return geojson.FeatureCollection(features)

    def _parse_waypoints_gpx(self, b):
        gpx = gpxpy.parse(b.decode('utf-8'))
        features = []
        for wpt in gpx.waypoints:
            pt = Point(wpt.longitude, wpt.latitude, wpt.elevation)
            properties = {
                'name': wpt.name,
                'description': wpt.description,
                'symbol': wpt.symbol,
            }
            features.append(geojson.Feature(geometry=pt, properties=properties))

        return geojson.FeatureCollection(features)

    def bbox_iter(self):
        """Get bounding box of each section
        """
        for section_name, gdf in self.trail_iter(alternates=True):
            yield section_name, gdf.unary_union.bounds

    def buffer_full(self, distance, unit='mile', alternates=True):
        """
        """
        trail = self.trail_full(alternates=alternates)
        buf = geom.buffer(trail, distance=distance, unit=unit).unary_union
        return buf

    def buffer_iter(self, distance, unit='mile', alternates=True):
        """Get buffer around each section
        """
        for section_name, gdf in self.trail_iter(alternates=alternates):
            buf = geom.buffer(gdf, distance=distance, unit=unit).unary_union
            yield section_name, buf

    @property
    def trk_geojsons(self):
        return sorted(self.line_dir.glob('*_tracks.geojson'))

    def _get_section(self, geojson_fname):
        # parse filename to get section
        sect_regex = re.compile(r'^(CA|OR|WA)_Sec_([A-Z])')
        state, letter = sect_regex.match(geojson_fname.stem).groups()
        section_id = f'{state}_{letter}'
        return section_id

    def _add_section_to_gdf(self, gdf, geojson_fname):
        section = self._get_section(geojson_fname)
        gdf['section'] = section
        return gdf

    def trail_iter(self, alternates=True):
        """Iterate over sorted trail sections
        """
        for f in self.trk_geojsons:
            gdf = gpd.read_file(f)
            section = self._get_section(f)
            gdf['section'] = section

            if not alternates:
                gdf = gdf[~gdf['alternate']]
            yield (section, gdf.to_crs(epsg=4326))

    def trail_full(self, alternates=True) -> gpd.GeoDataFrame:
        """Get Halfmile trail as GeoDataFrame
        """
        gdfs = []
        for f in self.trk_geojsons:
            gdf = gpd.read_file(f)
            gdf = self._add_section_to_gdf(gdf, f)
            gdfs.append(gdf)

        gdf = pd.concat(gdfs)
        if not alternates:
            gdf = gdf[~gdf['alternate']]

        return gdf.to_crs(epsg=4326)

    @property
    def wpt_geojsons(self):
        return sorted(self.point_dir.glob('*.geojson'))

    def wpt_iter(self):
        for f in self.wpt_geojsons:
            gdf = gpd.read_file(f)
            section = self._get_section(f)
            gdf['section'] = section
            yield (section, gdf.to_crs(epsg=4326))

    def wpt_full(self):
        gdfs = []
        for f in self.wpt_geojsons:
            gdf = gpd.read_file(f)
            gdf = self._add_section_to_gdf(gdf, f)
            gdfs.append(gdf)

        return pd.concat(gdfs).to_crs(epsg=4326)
