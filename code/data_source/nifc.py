from urllib.request import urlretrieve

import geopandas as gpd
from geopandas.tools import sjoin

from .base import DataSource


class NIFC(DataSource):
    """Historical fire perimeters from the National Interagency Fire Center

    The GeoMAC website is shutting down as of April 30, 2020. Instead, grab data
    from the National Interagency Fire Center.
    """
    def __init__(self):
        super(NIFC, self).__init__()

        self.raw_dir = self.data_dir / 'raw' / 'nifc'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, overwrite=False):
        # This URL has all perimeters ported from GeoMAC for the years 2000-2018.
        # https://data-nifc.opendata.arcgis.com/datasets/historic-geomac-perimeters-combined-2000-2018
        url = 'https://opendata.arcgis.com/datasets/ef25d7e8c9f3499ba9e3d8e09606e488_0.zip'
        fname = f'ef25d7e8c9f3499ba9e3d8e09606e488_0.zip'
        local_path = self.raw_dir / fname
        if overwrite or (not local_path.exists()):
            urlretrieve(url, local_path)

    def perimeters(self, geometry: gpd.GeoDataFrame, start_year=2010):
        """Get historical NIFC perimeters

        Args:
            - geometry: geometry to intersect with fires. No buffer is taken
              within this command. If you want a buffer around the trail, take
              the buffer before passing through here. Also, if you're merging
              CalFire data, you'd want to restrict the geometry to just Oregon
              and Washington before passing through here.
            - start_year: first year (inclusive) to keep fire perimeters for

        Returns:
            GeoDataFrame with fire perimeters since `start_year`.

            All columns are:
            - year: year of burn
            - name: name of burn in Title Case
            - acres: acre count of burn
            - firecode: some identifier, not sure exactly what
            - inciwebid: link to inciweb database, i.e.
              https://inciweb.nwcg.gov/incident/{inciwebid}/
            - geometry: geometry of burn
            - section: Halfmile section, i.e. `ca_a`
        """
        local_path = self.raw_dir / 'ef25d7e8c9f3499ba9e3d8e09606e488_0.zip'

        perims = gpd.read_file(
            f'zip://{str(local_path)}!Historic_GeoMAC_Perimeters_Combined_20002018.shp'
        )

        # Keep rows with non-null geometry
        perims = perims[perims.geometry.notna()]

        # Data covers 2000-2018
        # Keep fires since start_year
        perims = perims[perims['fireyear'] >= start_year]

        # Reproject to epsg 4326
        perims = perims.to_crs(epsg=4326)
        geometry = geometry.to_crs(epsg=4326)

        # Intersect with provided geometry
        # Note that when you intersect with this sjoin, if a geometry from
        # perims matches more than one geometry from `geometry`, it'll be listed
        # in the output data twice.
        # For example, the Eagle Creek fire intersects with both the Eagle Creek
        # Alternate and OR section G, and so it's shown up twice.
        perims_intersection = sjoin(perims, geometry, how='inner')

        # Deduplicate on uniquefire, datecurren,
        perims_intersection = perims_intersection.drop_duplicates(
            subset=['uniquefire', 'datecurren'])

        # Keep only necessary columns
        # 'section' is from the merge; is the Halfmile section
        cols_keep = [
            'fireyear', 'incidentna', 'gisacres', 'firecode', 'inciwebid',
            'geometry', 'section'
        ]
        perims_intersection = perims_intersection[cols_keep]
        perims_intersection = perims_intersection.rename(
            columns={
                'fireyear': 'year',
                'incidentna': 'name',
                'gisacres': 'acres'
            })

        # Make the name Title Case instead of UPPER CASE
        perims_intersection['name'] = perims_intersection['name'].str.title()

        return perims_intersection
