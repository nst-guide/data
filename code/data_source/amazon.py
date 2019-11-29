import os
from time import sleep

from dotenv import load_dotenv
from selenium.common.exceptions import ElementNotInteractableException

from .base import Scraper


class AmazonLockerScraper(Scraper):
    """
    Class to scrape locations and hours of Amazon Lockers

    The idea is that some trail towns may have Amazon lockers, and these are
    really convenient ways to ship items to yourself when you can't or don't
    want to ship to the post office.

    While this class implements automation of signing into Amazon.com and
    finding lockers, this should not be attempted with no human intervention.
    For one, I find that when trying to sign in with a throwaway account, Amazon
    always requires me to do two-factor authentication. They send a code to my
    email and I have to enter the code into the browser.

    With that in mind, this is essentially a quick way to search all the zip
    codes, after assistance logging in.

    The locker search page gives hours and addresses in plain text, but I
    believe latitudes and longitudes are stored server-side. With that in mind,
    I'll probably have to geocode these addresses after the scrape.

    Expected usage:
    ```py
    scraper = AmazonLockerScraper()
    scraper.sign_in() # check Chromedriver for 2fa prompt
    for zipcode in zipcodes:
        soup = scraper.search_lockers(zipcode)
        name, address, hours_dict = scraper.parse_locker_page(soup)
    ```
    """
    def __init__(self):
        super(AmazonLockerScraper, self).__init__()
        load_dotenv()
        self.username = os.getenv('AMAZON_USERNAME')
        self.password = os.getenv('AMAZON_PASSWORD')
        assert self.username is not None
        assert self.password is not None

        self.url = 'https://amazon.com/findalocker'

    def sign_in(self):
        self.get(self.url)
        email_box_css = '#ap_email'
        self.wait_for(email_box_css)
        self.send_keys(email_box_css, self.username)
        self.click('#continue')

        password_box_css = '#ap_password'
        self.wait_for(password_box_css)
        self.send_keys(password_box_css, self.password)
        self.click('#signInSubmit')

        # Should redirect to the search page automatically
        # self.get(self.url)
        zipcode_box_css = 'tr:nth-child(6) input'
        self.wait_for(zipcode_box_css)

    def search_lockers(self, zipcode):
        sleep(1.5)

        # Find zipcode search text field
        input_elements = self.driver.find_elements_by_tag_name('input')
        zip_elements = [
            x for x in input_elements if x.get_attribute('name') == 'storeZip'
        ]
        pasted = False
        for zip_element in zip_elements:
            try:
                zip_element.send_keys(zipcode)
                pasted = True
            except ElementNotInteractableException:
                pass

        if not pasted:
            raise ValueError('unable to find zipcode field to paste into')

        # Find search button
        search_button = [
            x for x in input_elements
            if x.get_attribute('name') == 'storeSearch'
        ]
        assert len(search_button) == 1
        search_button = search_button[0]
        search_button.click()

        return self.html()

    def parse_locker_page(self, soup):
        html = soup.find('html', recursive=False)
        body = html.find('body', recursive=False)

        # top-level tables
        # The first table containers header info; the second is the body of the
        # page
        tables1 = body.find_all('table', recursive=False)
        table1 = tables1[1]

        # The first table within table1 contains the whole left half of the page
        table2 = table1.find('table')

        # The next table contains all the results
        table3 = table2.find('table')

        # Further into the results
        table4 = table3.find('table')

        # Find table rows
        tbody = table4.find('tbody')
        trs = tbody.find_all('tr', recursive=False)

        # tr with colspan="6" are dividing lines
        trs = [tr for tr in trs if tr.find('td', colspan="6") is None]

        return (self.parse_row(tr) for tr in trs)

    def parse_row(self, tr):
        tds = tr.find_all('td', recursive=False)
        name_address = tds[1]

        name = list(name_address.children)[0].strip()
        address = list(name_address.children)[2].strip()

        hours = tds[3]
        [type(x) for x in list(hours.children)]
        from bs4.element import NavigableString
        navigable_strings = [x for x in hours.children if isinstance(x, NavigableString)]
        stripped = [x.strip() for x in navigable_strings if x.strip()]
        hours_dict = {}
        for day, times in zip(stripped[::2], stripped[1::2]):
            day = day.strip(':')
            hours_dict[day] = times

        return name, address, hours_dict
