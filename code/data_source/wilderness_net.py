from .base import PolygonSource, Scraper


class WildernessBoundaries(PolygonSource):
    def __init__(self):
        super(WildernessBoundaries, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound'
        self.url = 'http://www.wilderness.net/GIS/Wilderness_Areas.zip'
        self.filename = 'wilderness.geojson'

    def regulations(self):
        """Get regulations for each wilderness area from Wilderness Connect
        """
        gdf = self.polygon()
        scraper = WildernessConnectScraper()

        regs = []
        for row in gdf.itertuples(index=False):
            regulations = scraper.get_regulations(row.URL)
            regs.append(regulations)

        return regs


class WildernessConnectScraper(Scraper):
    """docstring for WildernessConnectScraper"""
    def __init__(self):
        super(WildernessConnectScraper, self).__init__()

    def get_regulations(self, url):
        """Get regulations for wilderness area from wilderness.net

        Args:
            - url: url to wilderness.net page on given Wilderness area. Should
              be sourced from wilderness.net boundaries file. E.g.:

              https://wilderness.net/visit-wilderness/?ID=382#area-management
        """
        self.get(url)
        regulations_selector = '#regulations'
        self.wait_for(regulations_selector)
        soup = self.html()
        regulations = soup.select(regulations_selector)
        return regulations
