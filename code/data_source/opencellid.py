import os
from urllib.request import urlretrieve

import pandas as pd
from dotenv import load_dotenv

from .base import DataSource


class CellTowers(DataSource):
    """
    References:
    http://wiki.opencellid.org/wiki/Menu_map_view#database
    """
    def __init__(self):
        super(CellTowers, self).__init__()
        self.save_dir = self.data_dir / 'raw' / 'cell_towers'
        self.save_dir.mkdir(parents=True, exist_ok=True)

        load_dotenv()
        self.api_key = os.getenv('OPENCELLID_API_KEY')
        assert self.api_key is not None, 'OpenCellID api key not loaded from .env'

        self.mccs = [302, 310, 311, 312, 313, 316]

    def download(self, overwrite=False):
        url = 'https://opencellid.org/ocid/downloads?token='
        url += f'{self.api_key}&type=mcc&file='
        for mcc in self.mccs:
            stub = f'{mcc}.csv.gz'
            if overwrite or (not (self.save_dir / stub).exists()):
                urlretrieve(url + stub, self.save_dir / stub)

    def download_mobile_network_codes(self):
        url = 'https://en.wikipedia.org/wiki/Mobile_Network_Codes_in_ITU_region_3xx_(North_America)'
        # Get the Wikipedia table with a row that matches "Verizon Wireless"
        dfs = pd.read_html(url, match='Verizon Wireless')
        assert len(
            dfs) == 1, 'More than one match in wikipedia cell network tables'
        df = dfs[0]

        path = self.save_dir / 'network_codes.csv'
        df.to_csv(path, index=False)
