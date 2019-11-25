from time import sleep

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import ElementNotVisibleException

from .base import PolygonSource


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
            scraper.get(row.URL)
            regs.append(scraper.regulations())

        return regs


class WildernessConnectScraper:
    """docstring for WildernessConnectScraper"""
    def __init__(self):
        super(WildernessConnectScraper, self).__init__()
        self.driver = webdriver.Chrome()

    url = 'https://wilderness.net/visit-wilderness/?ID=382#area-management'

    def get(self, url):
        # Go to wilderness page
        self.driver.get(url)
        self._wait_for_load(css_selector='#regulations')
        soup = BeautifulSoup(self.driver.page_source, 'lxml')
        self._get_regulations(soup)

    def _wait_for_load(self, css_selector):
        try:
            regs = self.driver.find_element_by_css_selector(css_selector)
        except ElementNotVisibleException:
            sleep(1)
            self._wait_for_load()

    def _get_regulations(self, soup):
        regs = soup.select('#regulations')
        assert len(regs) == 1, '#regulations gives >1 result'
        regs = regs[0]

        print(regs.text)
