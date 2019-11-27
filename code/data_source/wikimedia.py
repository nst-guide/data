import math
from typing import List
from urllib.parse import urlparse
from urllib.request import urlretrieve

import wikipedia
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

        return wikipedia.page(res[choice])

    def page(self, title):
        """Simple page wrapper around wikipedia.page"""
        if not isinstance(title, str):
            raise TypeError('title must be str')

        return wikipedia.page(title)

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
        circles = geom.find_circles_that_tile_polygon(polygon, radius=10000)
        titles = set()
        for circle, radius in circles:
            res = self.find_page_titles_around_point(
                point=circle.centroid, radius=math.ceil(radius))
            titles.update(res)

        pages = [wikipedia.page(title) for title in titles]
        # [::-1] because returned as lat, lon. Point requires lon, lat
        # "To test one polygon containment against a large batch of points, one
        # should first use the prepared.prep() function"
        prepared_polygon = prep(polygon)
        pages = [
            page for page in pages
            if prepared_polygon.contains(Point(page.coordinates[::-1]))
        ]
        return pages
