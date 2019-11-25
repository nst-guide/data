from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlretrieve

import fiona
import geopandas as gpd
from geopandas.tools import sjoin

import geom
from halfmile import Halfmile


def in_ipython():
    try:
        return __IPYTHON__
    except NameError:
        return False


def find_data_dir():
    if in_ipython():
        # Note, this will get the path of the file this is called from;
        # __file__ doesn't exist in IPython
        cwd = Path().absolute()
    else:
        cwd = Path(__file__).absolute()

    data_dir = (cwd / '..' / 'data').resolve()
    return data_dir


class DataSource:
    def __init__(self):
        self.data_dir = find_data_dir()


class PolygonSource(DataSource):
    def __init__(self):
        super(PolygonSource, self).__init__()
        self.save_dir = None
        self.url = None
        self.filename = None
        self.raw_dir = self.data_dir / 'raw' / 'polygon'
        self.raw_dir.mkdir(exist_ok=True, parents=True)

    def download(
            self,
            trail: gpd.GeoDataFrame,
            buffer_dist=None,
            buffer_unit='mile',
            overwrite=False):
        """Download polygon shapefile and intersect with PCT track
        """
        assert self.save_dir is not None, 'self.save_dir must be set'
        assert self.url is not None, 'self.url must be set'
        assert self.filename is not None, 'self.filename must be set'

        # Cache original download in self.raw_dir
        parsed_url = urlparse(self.url)
        raw_fname = Path(parsed_url.path).name
        raw_path = self.raw_dir / raw_fname
        if overwrite or (not raw_path.exists()):
            urlretrieve(self.url, raw_path)

        # Now load the saved file as a GeoDataFrame
        with open(raw_path, 'rb') as f:
            with fiona.BytesCollection(f.read()) as fcol:
                crs = fcol.crs
                gdf = gpd.GeoDataFrame.from_features(fcol, crs=crs)

        # Reproject to WGS84
        gdf = gdf.to_crs(epsg=4326)

        # Load Halfmile track for intersections
        trail = Halfmile().trail_full(alternates=True)
        trail = trail.to_crs(epsg=4326)

        # Intersect with the trail
        if buffer_dist is not None:
            buf = geom.buffer(trail, distance=buffer_dist, unit=buffer_unit)
            # Returned as GeoSeries; coerce to GDF
            if not isinstance(buf, gpd.GeoDataFrame):
                buf = gpd.GeoDataFrame(geometry=buf)
                buf = buf.to_crs(epsg=4326)

            intersection = sjoin(gdf, buf, how='inner')
        else:
            intersection = sjoin(gdf, trail, how='inner')

        # Do any specific steps, to be overloaded in subclasses
        intersection = self._post_download(intersection)

        # Save to GeoJSON
        self.save_dir.mkdir(exist_ok=True, parents=True)
        intersection.to_file(self.save_dir / self.filename, driver='GeoJSON')

    def _post_download(self, gdf):
        """Situation specific post-download steps

        To be overloaded in subclasses
        """
        return gdf

    def polygon(self) -> gpd.GeoDataFrame:
        """Load Polygon as GeoDataFrame
        """
        path = self.save_dir / self.filename
        polygon = gpd.read_file(path)
        return polygon
