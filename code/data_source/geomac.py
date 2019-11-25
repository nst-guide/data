from io import BytesIO
from urllib.request import urlretrieve
from zipfile import ZipFile

import geojson
import requests
from bs4 import BeautifulSoup
from fastkml import kml

from .base import DataSource


class GeoMAC(DataSource):
    def __init__(self):
        super(GeoMAC, self).__init__()

        self.raw_dir = self.data_dir / 'raw' / 'geomac'
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download_historical_data(self, overwrite=False):
        baseurl = 'https://rmgsc.cr.usgs.gov/outgoing/GeoMAC/'
        baseurl += 'historic_fire_data/'

        for year in range(2000, 2019):
            fname = f'{year}_perimeters_dd83.zip'
            local_path = self.raw_dir / fname
            url = baseurl + fname
            if overwrite or (not local_path.exists()):
                urlretrieve(url, local_path)

            # Starting with 2002, the `sit_rep_pts` file also exists
            if year >= 2002:
                fname = f'{year}_sit_rep_pts_dd83.zip'
                local_path = self.raw_dir / fname
                url = baseurl + fname
                if overwrite or (not local_path.exists()):
                    urlretrieve(url, local_path)

    def get_active_perimeters(self):
        url = 'https://rmgsc.cr.usgs.gov/outgoing/GeoMAC/'
        url += 'ActiveFirePerimeters.kmz'
        r = requests.get(url)

        k = kml.KML()
        with ZipFile(BytesIO(r.content)) as z:
            names = z.namelist()
            assert len(names) == 1
            k.from_string(z.read(names[0]))

        featurecollection = []
        for document in k.features():
            for placemark in document.features():
                properties = {
                    'placemark_name': placemark.name,
                    'style_id': placemark.styleUrl.replace('#', ''),
                }
                desc = self._parse_description(placemark.description)
                properties.update(desc)

                json_feature = geojson.Feature(
                    geometry=placemark.geometry, properties=properties)
                featurecollection.append(json_feature)

        return geojson.FeatureCollection(features=featurecollection)

    def _parse_description(self, desc):
        soup = BeautifulSoup(desc)
        lines = soup.text.split('\n')
        lines = [x.strip() for x in lines]
        lines = [x for x in lines if x]

        # Remove first line, the 'b' tag
        lines = [x for x in lines if x != soup.find('b').text]

        # Remove text from links, the 'a' tags
        lines = [
            x for x in lines if x not in [a.text for a in soup.find_all('a')]
        ]

        # Now it's just key-values separated by a colon
        # Split on first colon
        info = [l.split(': ', 1) for l in lines]
        d = {}
        for line in info:
            if len(line) == 1:
                continue
            k, v = line
            d[k.lower().replace(' ', '_')] = v

        return d
