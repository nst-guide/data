import geopandas as gpd
import pandas as pd

from .base import DataSource, PolygonSource


class StatePlaneZones(DataSource):
    """docstring for StatePlaneZones"""
    def __init__(self):
        super(StatePlaneZones, self).__init__()

    def downloaded(self):
        return (self.data_dir / 'proj' / 'state_planes.geojson').exists()

    def download(self):
        # Helpful list of state planes and their boundaries
        url = 'http://sandbox.idre.ucla.edu/mapshare/data/usa/other/spcszn83.zip'
        zones = gpd.read_file(url)
        epsg_zones = pd.read_csv(self.data_dir / 'proj' / 'state_planes.csv')
        zones = zones.merge(
            epsg_zones, left_on='ZONENAME', right_on='zone', validate='1:1')

        minimal = zones[['geometry', 'epsg', 'zone']]
        minimal = minimal.rename(columns={'zone': 'name'})
        minimal.to_file(
            self.data_dir / 'proj' / 'state_planes.geojson', driver='GeoJSON')


class StateBoundaries(PolygonSource):
    def __init__(self):
        super(StateBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.url = 'https://www2.census.gov/geo/tiger/TIGER2017//STATE/tl_2017_us_state.zip'
        self.filename = 'state.geojson'


class ZipCodeTabulationAreas(PolygonSource):
    """
    Note: when downloading, you should pass
    towns = Towns().boundaries()

    ```
    trail=towns
    buffer_dist=None
    buffer_unit='mile'
    overwrite=False
    ```
    """
    def __init__(self):
        super(ZipCodeTabulationAreas, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'attrs'
        stub = 'cb_2018_us_zcta510_500k.zip'
        self.url = 'https://www2.census.gov/geo/tiger/GENZ2018/shp/' + stub
        self.filename = 'zcta.geojson'
