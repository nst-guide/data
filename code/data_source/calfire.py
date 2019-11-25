from pathlib import Path
from urllib.request import urlretrieve

import geopandas as gpd

from base import DataSource


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

    def perimeters(self):
        local_path = self.raw_dir / 'fire18_1.zip'
        perimeters = gpd.read_file(f'zip://{str(local_path)}!fire18_1.gdb')
        import geopandas as gpd
        perimeters = gpd.read_file(
            'zip:///Users/kyle/github/mapping/nst-guide/create-database/data/raw/calfire/fire18_1.zip!fire18_1.gdb'
        )
        dict(perimeters['YEAR_'].value_counts())
        perimeters
        Visualize(perimeters)
