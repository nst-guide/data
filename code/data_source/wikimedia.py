import math
from typing import List
from urllib.parse import urlparse
from urllib.request import urlretrieve

import wikipedia
from bs4 import BeautifulSoup
from shapely.geometry import Point
from shapely.prepared import prep

from .base import DataSource

try:
    import geom
    from util import normalize_string
except ModuleNotFoundError:
    # Development in IPython
    import sys
    sys.path.append('../')
    import geom
    from util import normalize_string


class Wikipedia(DataSource):
    """
    Wrapper to access the Wikipedia API

    No type checking is done in the wikipedia module, and passing something
    other than a string raises a very obscure error that makes debugging
    difficult, so I do some simple type checking before passing things to the
    wikipedia module.
    """
    def __init__(self):
        super(Wikipedia, self).__init__()
        self.image_dir = self.data_dir / 'raw' / 'wikipedia' / 'images'

    def find_page_by_name(self, name: str, point=None, radius=None):
        """Find a single Wikipedia page given a name

        Search for the top 5 results. If there's a result with the exact same
        normalized name, choose that article. Otherwise, choose the first
        result.

        Note that even when the name is not exactly the same, the first result
        usually makes sense. For example, the first result for "Mount Rainier
        Wilderness" is "Mount Rainier National Park". And it would be ok to show
        the wikipedia page for the National Park when a user clicks on the
        wilderness polygon.

        Args:
            - name: name to search for
            - point: point in WGS84 to search around
            - radius: radius in meters to search around point
        """
        if not isinstance(name, str):
            raise TypeError('name must be str')
        if point is not None:
            if not isinstance(point, Point):
                raise TypeError('point must be of type Point')

        if point is None:
            res = wikipedia.search(name, results=5)
        else:
            lon, lat = list(point.coords)[0]
            radius = 400 if radius is None else radius
            res = wikipedia.geosearch(
                latitude=lat,
                longitude=lon,
                title=name,
                results=5,
                radius=radius)

        exact_match = [
            ind for ind, s in enumerate(res)
            if normalize_string(s) == normalize_string(name)
        ]
        choice = None
        if exact_match != []:
            choice = exact_match[0]
        else:
            choice = 0

        # Here turn auto_suggest to False because I know the page name exists
        # Otherwise sometimes the page names redirect from a name that exists to
        # a name that does not. For example, searching
        # ```
        # wikipedia.page('Shasta-Trinity National Forest')
        # ```
        # raises `PageError: Page id "shasta trinity national forests" does not
        # match any pages. Try another id!`, while the page does exist:
        # https://en.wikipedia.org/wiki/Shasta%E2%80%93Trinity_National_Forest
        # See also
        # https://github.com/goldsmith/Wikipedia/issues/192
        # https://github.com/goldsmith/Wikipedia/issues/176
        return wikipedia.page(res[choice], auto_suggest=False)

    def page(self, title, auto_suggest=False):
        """Simple page wrapper around wikipedia.page

        Args:
            - title: page title
            - auto_suggest: let Wikipedia find a valid page title for the query.
              This should be False if you know the page title exists.
        """
        if not isinstance(title, str):
            raise TypeError('title must be str')

        return wikipedia.page(title, auto_suggest=auto_suggest)

    def get_html_for_page(self, page: wikipedia.WikipediaPage):
        """Construct HTML for page

        TODO: Fix HTML links so that images and external links work correctly.
        For example, current wiki links are `href="/wiki/Mount_Lago"`, and that
        should be changed to `href="wikipedia.org/wiki/Mount_Lago"`. Note that
        it would be cool if you were able to check if the page pointed to is
        also in the Wikipedia extract, because then you could link to it
        offline!?!?
        """
        if not isinstance(page, wikipedia.WikipediaPage):
            raise TypeError('page must be of type wikipedia.WikipediaPage')

        html = page.html()

        # Download images
        image_paths = self._download_images(page.images)

        # Fix links
        html = self._fix_links(html, image_paths)

        return html

    def _fix_links(self, html):
        """Fix links in Wikipedia page HTML
        """
        return html

    def _download_images(self, images: List[str]):
        """Download linked images from Wikipedia page

        Args:
            - images: list of URLs to Wikipedia page images
        """
        local_paths = []
        for image_url in images:
            parsed = urlparse(image_url)
            local_path = str(self.image_dir) + parsed.path
            local_paths.append(local_path)
            if not local_path.exists():
                urlretrieve(image_url, local_path)

        return local_paths

    def find_page_titles_around_point(
            self, point: Point, title=None, results=None,
            radius=10000) -> List[str]:
        """Find pages around point using Wikipedia Geosearch

        Args:
            - point: geographic point to search around
            - title: optional title of nearby page
            - results: max number of results. Not sure if None is unlimited
            - radius: search radius in meters. Between 10 and 10,000

        Returns:
            - Page _titles_ around point. Loading actual page metadata is
              slower, so that can be done in a later function, in case I want to
              get just titles to filter.
        """
        if not isinstance(point, Point):
            raise TypeError('point must be of type Point')
        if title is not None:
            if not isinstance(title, str):
                raise TypeError('title must be str')

        assert isinstance(point, Point), 'point must have Point geometry'
        lon, lat = list(point.coords)[0]

        res = wikipedia.geosearch(
            latitude=lat,
            longitude=lon,
            title=title,
            results=results,
            radius=radius)
        return res

    def find_pages_for_polygon(self, polygon):
        """Find pages within polygon using repeated Geosearch

        The Geosearch API has no polygon support; only point. To get around
        this, I first find a collection of circles that together tile the
        polygon, then for each circle I call the geosearch API.
        """
        # When set to radius=10000, I got an error from the wikipedia API
        points, radii = geom.find_circles_that_tile_polygon(
            polygon, radius=10000)

        titles = set()
        for point, radius in zip(points, radii):
            radius = math.ceil(radius)
            res = self.find_page_titles_around_point(point=point, radius=radius)
            titles.update(res)

        # Get wikipedia page metadata for each of the titles I've found above
        # Occasionally you get a disambiguation error, because the search is by
        # title?
        # Note, since I've already found titles that I know exist, I should set
        # auto_suggest=False
        pages = []
        for title in titles:
            try:
                pages.append(wikipedia.page(title, auto_suggest=False))
            except wikipedia.WikipediaException:
                pass

        # Make sure that all returned articles are within the original polygon
        # [::-1] because returned as lat, lon. Point requires lon, lat
        # "To test one polygon containment against a large batch of points, one
        # should first use the prepared.prep() function"
        prepared_polygon = prep(polygon)
        new_pages = []
        for page in pages:
            try:
                if prepared_polygon.contains(Point(page.coordinates[::-1])):
                    new_pages.append(page)
            # Occasionally the page won't have a coordinates attribute
            except KeyError:
                pass

        return new_pages

    def best_image_on_page(self, page):
        """Try to find best image on wikipedia page
        """
        # If page has no images, return None
        if len(page.images) == 0:
            return None

        # Get page html
        html = page.html()
        soup = BeautifulSoup(html, 'lxml')

        # Try to find best image
        # If an info box exists, get the first image inside the infobox
        # Otherwise get the first image on page
        # Just getting the first image on page isn't ideal because the first
        # image can be inside the "This article needs additional citations for
        # verification" box
        table = soup.find('table', attrs={'class': 'infobox'})
        if table:
            first_img = table.find('img')
        else:
            first_img = soup.find('img')

        if not first_img:
            return None

        # The alt text should be the same as the stub of an image url
        img_src = first_img.attrs['src']

        # Split into sections by / and get first section that ends in jpg, png
        # or svg
        # If none is found, return the first image from list
        name = next((
            x for x in img_src.split('/') if any(
                x.lower().endswith(ext) for ext in ['.jpg', '.png', '.svg'])),
                    page.images[0])

        # Find image url of first image
        first_image_url = [x for x in page.images if name in x]
        assert len(first_image_url) == 1, 'error finding first image on page'

        return first_image_url[0]
