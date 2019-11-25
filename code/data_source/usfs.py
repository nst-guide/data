from pathlib import Path
from urllib.request import urlretrieve

import geopandas as gpd
from fiona.io import ZipMemoryFile

import geom
from base import DataSource, PolygonSource


class USFS(DataSource):
    """docstring for USFS"""
    def __init__(self):
        super(USFS, self).__init__()
        self.raw_dir = self.data_dir / 'raw' / 'usfs'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def downloaded(self) -> bool:
        save_dir = self.data_dir / 'pct' / 'line' / 'usfs'
        files = ['trail.geojson']
        return all((save_dir / f).exists() for f in files)

    def download(self, overwrite=False):
        url = 'https://www.fs.usda.gov/Internet/FSE_DOCUMENTS/stelprdb5332131.zip'
        local_path = self.raw_dir / Path(url).name
        if overwrite or (not local_path.exists()):
            urlretrieve(url, local_path)

        with open(local_path, 'rb') as f:
            with ZipMemoryFile(f.read()) as z:
                with z.open('PacificCrestTrail.shp') as collection:
                    crs = collection.crs
                    fc = list(collection)

        gdf = gpd.GeoDataFrame.from_features(fc, crs=crs)
        gdf = gdf.to_crs(epsg=4326)

        save_dir = self.data_dir / 'pct' / 'line' / 'usfs'
        save_dir.mkdir(parents=True, exist_ok=True)
        gdf.to_file(save_dir / 'trail.geojson', driver='GeoJSON')

    def trail(self) -> gpd.GeoDataFrame:
        """Load trail into GeoDataFrame"""
        save_dir = self.data_dir / 'pct' / 'line' / 'usfs'
        return gpd.read_file(save_dir / 'trail.geojson').to_crs(epsg=4326)

    def buffer(self, distance: float = 20) -> gpd.GeoDataFrame:
        """Load cached buffer

        If the buffer doesn't yet exist, creates it and saves it to disk

        Args:
            distance: buffer radius in miles

        Returns:
            GeoDataFrame with buffer geometry
        """
        path = self.data_dir / 'pct' / 'polygon' / 'usfs' / f'buffer{distance}mi.geojson'
        if not path.exists():
            self._create_buffer(distance=distance)

        return gpd.read_file(path)

    def _create_buffer(self, distance: float = 20):
        """Create buffer around USFS pct track

        Args:
            distance: buffer radius in miles
        """
        trail = self.trail()
        buffer = geom.buffer(trail, distance=20, unit='mile')

        save_dir = self.data_dir / 'pct' / 'polygon' / 'usfs'
        save_dir.mkdir(parents=True, exist_ok=True)

        buffer.to_file(
            save_dir / f'buffer{distance}mi.geojson', driver='GeoJSON')


class NationalForestBoundaries(PolygonSource):
    def __init__(self):
        super(NationalForestBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.url = 'https://data.fs.usda.gov/geodata/edw/edw_resources/shp/S_USA.AdministrativeForest.zip'
        self.filename = 'nationalforest.geojson'
