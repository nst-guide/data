# Scraping code

from pathlib import Path

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import ElementNotVisibleException


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
