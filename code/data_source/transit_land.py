from time import sleep

import geojson
import requests
from shapely.geometry import shape

from .base import DataSource


class Transit(DataSource):
    """
    TODO: update API calls to page if necessary. Currently the max results is
    just set high.
    """
    def __init__(self):
        super(Transit, self).__init__()

    def download(self, geometry):
        """Create trail-relevant transit dataset from transit.land database

        Args:
            - geometry: geometry around which to find transit services. A
              transit _stop_ must intersect this geometry. For this reason, you
              should probably provide a polygon geometry, not a LineString.

              Note that not all of the transit line needs to be within the
              geometry. This finds all routes that have at least one stop
              intersecting the geometry, but then grabs all routes that serve
              the selected stop.
        """
        # Find operators that intersect provided geometry
        operators_intersecting_geom = self.get_operators_intersecting_geometry(
            geometry)

        # For each operator, see if there are actually transit stops that
        # intersect the provided geometry
        intersecting_stops = []
        for operator in operators_intersecting_geom:
            stops = self.get_stops_intersecting_geometry(
                geometry=geometry, operator_id=operator['onestop_id'])
            if len(stops) > 0:
                intersecting_stops.extend(stops)

        # For each stop that intersects the geometry, add it to the nearby_stops
        # dict
        # For each route that stops at each nearby stop, get information about
        # the route and add it to the routes dict
        nearby_stops = {}
        routes = {}
        for stop in intersecting_stops:
            # Add stop to the self.nearby_stops dict
            nearby_stops[stop['onestop_id']] = stop

            # Get more info about each route that stops at stop
            # Routes are added to self.routes
            for route_dict in stop['routes_serving_stop']:
                route_id = route_dict['route_onestop_id']
                routes[route_id] = self.get_route_from_id(route_id=route_id)

        # For each stop along each route, get the id's of all stops.
        # {stop_onestop_id: stop}
        all_stops = {}
        for route in routes.values():
            route_stops = route['stops_served_by_route']
            for route_stop in route_stops:
                route_stop_id = route_stop['stop_onestop_id']
                all_stops[route_stop_id] = self.get_stop_from_id(
                    stop_id=route_stop_id)

        nearby_stops = self.update_stop_info(nearby_stops)
        stops = self.update_stop_info(stops)

        return intersecting_stops, nearby_stops, routes

    def get_operators_intersecting_geometry(self, geometry):
        """Find transit operators with service area crossing provided geometry

        Using the transit.land API, you can find all transit operators within a
        bounding box. Since the bbox of the PCT is quite large, I then check the
        service area polygon of each potential transit operator to see if it
        intersects the trail.

        Args:
            - geometry: Shapely geometry object of some type
        """
        # Create stringified bbox
        bbox = ','.join(map(str, geometry.bounds))

        url = 'https://transit.land/api/v1/operators'
        params = {'bbox': bbox, 'per_page': 10000}
        d = self.request_transit_land(url, params=params)

        operators_intersecting_geom = []
        for operator in d['operators']:
            # Check if the service area of the operator intersects trail
            operator_geom = shape(operator['geometry'])
            intersects = geometry.intersects(operator_geom)
            if intersects:
                operators_intersecting_geom.append(operator)

        return operators_intersecting_geom

    def get_stops_intersecting_geometry(self, geometry, operator_id):
        """Find all stops by operator that intersect geometry

        Args:
            - geometry: shapely geometry object to take intersections with
            - operator_id: onestop operator id
        """
        url = 'https://transit.land/api/v1/stops'
        params = {'served_by': operator_id, 'per_page': 10000}
        d = self.request_transit_land(url, params=params)

        intersecting_stops = []
        for stop in d['stops']:
            stop_geometry = shape(stop['geometry'])
            intersects = geometry.intersects(stop_geometry)

            if intersects:
                intersecting_stops.append(stop)

        return intersecting_stops

    def get_route_from_id(self, route_id):
        """Find route info from route_id

        Args:
            - route_id: onestop id for a route
        """
        url = f'https://transit.land/api/v1/onestop_id/{route_id}'
        return self.request_transit_land(url)

    def get_stop_from_id(self, stop_id):
        """Find stop info from stop_id

        Args:
            - stop_id: onestop id for a stop
        """
        url = f'https://transit.land/api/v1/onestop_id/{stop_id}'
        return self.request_transit_land(url)

    def update_stop_info(self, stops):
        """Update stop information from Transit land

        For every value of stops that is None, search for the key in
        transit.land.

        Args:
            - stops: dict {stop_onestop_id: None or stop_info}

        Returns:
            dict {stop_onestop_id: stop_info}
        """
        for stop_id, value in stops.items():
            if value is not None:
                continue

            url = f'https://transit.land/api/v1/onestop_id/{stop_id}'
            d = self.request_transit_land(url)
            stops[stop_id] = d

        return stops

    def get_schedules(self):
        """Get schedules to add to route and stop data

        TODO figure out the best way to collect and store this
        """
        url = 'https://transit.land/api/v1/schedule_stop_pairs'
        for route_id in self.routes.keys():
            params = {'route_onestop_id': route_id, 'per_page': 10000}
            r = requests.get(url, params=params)
            d = r.json()

    def get_geojson_for_routes(self, routes):
        """Create FeatureCollection from self.routes for inspection
        """
        features = []
        for route_id, route in self.routes.items():
            properties = {
                'onestop_id': route['onestop_id'],
                'name': route['name'],
                'vehicle_type': route['vehicle_type'],
                'operated_by_name': route['operated_by_name'],
            }
            feature = geojson.Feature(
                geometry=route['geometry'], properties=properties)
            features.append(feature)
        return geojson.FeatureCollection(features)

    def request_transit_land(self, url, params=None):
        """Wrapper for requests to transit.land API to stay within rate limit

        You can make 60 requests per minute to the transit.land API, which
        presumably resets after each 60-second period. (It's not per 1-second
        period, because I was able to make 60 requests in like 10 seconds).

        Given this, when I hit r.status_code, I'll sleep for 2 seconds before
        trying again.

        Args:
            - url: url to send requests to
            - params: None or dict of params for sending requests

        Returns:
            dict of transit.land output
        """
        r = requests.get(url, params=params)
        if r.status_code == 429:
            sleep(2)
            return self.request_transit_land(url, params=params)

        return r.json()
