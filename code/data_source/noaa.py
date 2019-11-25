from urllib.request import urlretrieve

import pandas as pd

from base import DataSource
from grid import TenthDegree


class LightningCounts(DataSource):
    """

    NOAA publishes daily counts of lightning strikes within .1-degree lat/lon
    grid cells.
    https://www.ncdc.noaa.gov/data-access/severe-weather/lightning-products-and-services

    """
    def __init__(self):
        super(LightningCounts, self).__init__()
        self.save_dir = self.data_dir / 'raw' / 'lightning'
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def downloaded(self) -> bool:
        return False

    def download(self, overwrite=False):
        url = 'https://www1.ncdc.noaa.gov/pub/data/swdi/database-csv/v2/'
        for year in range(1986, 2019):
            stub = f'nldn-tiles-{year}.csv.gz'
            if overwrite or (not (self.save_dir / stub).exists()):
                urlretrieve(url + stub, self.save_dir / stub)

    def read_data(self, year) -> pd.DataFrame:
        """Read lightning data and return daily count for PCT cells
        """
        stub = f'nldn-tiles-{year}.csv.gz'
        df = pd.read_csv(self.save_dir / stub, compression='gzip', skiprows=2)
        rename_dict = {
            '#ZDAY': 'date',
            'CENTERLON': 'lon',
            'CENTERLAT': 'lat',
            'TOTAL_COUNT': 'count'
        }
        df = df.rename(columns=rename_dict)
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        # Keep only the cells intersecting the trail
        # TODO: take the following get_cells() outside of this function because
        # it's slow
        centerpoints = TenthDegree().get_cells()
        center_df = pd.DataFrame(centerpoints, columns=['lon', 'lat'])

        merged = df.merge(center_df, how='inner')
        return merged
