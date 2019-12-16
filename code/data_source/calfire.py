from pathlib import Path
from urllib.request import urlretrieve

import geopandas as gpd
import pandas as pd
from geopandas.tools import sjoin

from .base import DataSource


class CalFire(DataSource):
    def __init__(self):
        super(CalFire, self).__init__()

        self.raw_dir = self.data_dir / 'raw' / 'calfire'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, overwrite=False):
        url = 'https://frap.fire.ca.gov/media/2525/fire18_1.zip'
        local_path = self.raw_dir / Path(url).name
        if overwrite or (not local_path.exists()):
            urlretrieve(url, local_path)

    def perimeters(self, geometry: gpd.GeoDataFrame, start_year=2010):
        """Get CalFire perimeters

        Args:
            - geometry: geometry to intersect with fires. No buffer is taken
              within this command. If you want a buffer around the trail, take
              the buffer before passing through here.
            - start_year: first year (inclusive) to keep fire perimeters for

        Returns:
            GeoDataFrame with fire perimeters since `start_year`.

            Both prescribed burns and non-prescribed burns are included.

            All columns are:
            - year: year of burn
            - name: name of burn in Title Case
            - acres: acre count of burn
            - geometry: geometry of burn
            - section: Halfmile section, i.e. `ca_a`
            - rx: if True, is a prescribed burn
        """
        local_path = self.raw_dir / 'fire18_1.zip'
        perims = gpd.read_file(
            f'zip://{str(local_path)}!fire18_1.gdb', layer='firep18_1')

        rxburn = gpd.read_file(
            f'zip://{str(local_path)}!fire18_1.gdb', layer='rxburn18_1')

        # Keep rows with non-null geometry
        perims = perims[perims.geometry.notna()]
        rxburn = rxburn[rxburn.geometry.notna()]

        # Data goes back a long way. Keep fires since 2010
        # Cast year column to numeric
        perims['YEAR_'] = pd.to_numeric(perims['YEAR_'], errors='coerce')
        rxburn['YEAR_'] = pd.to_numeric(rxburn['YEAR_'], errors='coerce')
        # Keep since 2010
        perims = perims[perims['YEAR_'] >= start_year]
        rxburn = rxburn[rxburn['YEAR_'] >= start_year]

        # Reproject to epsg 4326
        perims = perims.to_crs(epsg=4326)
        rxburn = rxburn.to_crs(epsg=4326)
        geometry = geometry.to_crs(epsg=4326)

        # Intersect with provided geometry
        perims_intersection = sjoin(perims, geometry, how='inner')
        rxburn_intersection = sjoin(rxburn, geometry, how='inner')

        # Keep only necessary columns
        # 'section' is from the merge; is the Halfmile section
        perims_cols_keep = [
            'YEAR_', 'FIRE_NAME', 'GIS_ACRES', 'geometry', 'section'
        ]
        perims_intersection = perims_intersection[perims_cols_keep]
        perims_intersection.loc[:, 'rx'] = False
        perims_intersection = perims_intersection.rename(
            columns={
                'YEAR_': 'year',
                'FIRE_NAME': 'name',
                'GIS_ACRES': 'acres'
            })

        rxburn_cols_keep = [
            'YEAR_', 'TREATMENT_NAME', 'GIS_ACRES', 'geometry', 'section'
        ]
        rxburn_intersection = rxburn_intersection[rxburn_cols_keep]
        rxburn_intersection.loc[:, 'rx'] = True
        rxburn_intersection = rxburn_intersection.rename(
            columns={
                'YEAR_': 'year',
                'TREATMENT_NAME': 'name',
                'GIS_ACRES': 'acres'
            })

        combined = gpd.GeoDataFrame(
            pd.concat([perims_intersection, rxburn_intersection], sort=False))
        # Make the name Title Case instead of UPPER CASE
        combined['name'] = combined['name'].str.title()

        return combined
