import json

import geojson
import geopandas as gpd
import requests
from haversine import haversine
from shapely.geometry import LineString, shape

from .base import DataSource


class Transit(DataSource):
    def __init__(self):
        super(Transit, self).__init__()

        self.routes = {}
        self.nearby_stops = {}
        self.all_stops = {}
        self.operators = {}

    def download(self, trail: gpd.GeoDataFrame):
        """Create trail-relevant transit dataset from transit.land database
        """
        # Find operators that intersect trail
        trail_line = trail.unary_union
        operators_near_trail = self.get_operators_near_trail(trail_line)

        # For each operator, see if there are actually transit stops within a
        # walkable distance from the trail (currently set to 1000m)
        for operator in operators_near_trail:
            # First, see if this operator actually has stops near the trail
            stops = self.get_stops_near_trail(
                operator['onestop_id'], distance=1000)
            if len(stops) == 0:
                continue

            for stop in stops:
                # Add stop to the self.nearby_stops dict
                stop_id = stop['onestop_id']
                self.nearby_stops[stop_id] = stop

                # Get more info about each route that stops at stop
                # Routes are added to self.routes
                self.get_routes_for_stop(stop)

        self.update_stop_information()
        # self.get_schedules()

        # Serialize everything to disk
        save_dir = self.data_dir / 'pct' / 'line' / 'transit'
        save_dir.mkdir(parents=True, exist_ok=True)

        with open(save_dir / 'routes.json', 'w') as f:
            json.dump(self.routes, f)
        with open(save_dir / 'nearby_stops.json', 'w') as f:
            json.dump(self.nearby_stops, f)
        with open(save_dir / 'all_stops.json', 'w') as f:
            json.dump(self.all_stops, f)

    def get_operators_near_trail(self, trail_line: LineString):
        """Find transit operators with service area crossing the trail

        Using the transit.land API, you can find all transit operators within a
        bounding box. Since the bbox of the PCT is quite large, I then check the
        service area polygon of each potential transit operator to see if it
        intersects the trail.
        """
        trail_bbox = trail_line.bounds
        trail_bbox = [str(x) for x in trail_bbox]

        url = 'https://transit.land/api/v1/operators'
        params = {'bbox': ','.join(trail_bbox), 'per_page': 10000}
        r = requests.get(url, params=params)
        d = r.json()

        operators_on_trail = []
        for operator in d['operators']:
            # Check if the service area of the operator intersects trail
            operator_polygon = shape(operator['geometry'])
            intersects_trail = trail_line.intersects(operator_polygon)
            if intersects_trail:
                operators_on_trail.append(operator)

        return operators_on_trail

    def get_stops_near_trail(
            self, trail_line: LineString, operator_id, distance=1000):
        """Find all stops in Transitland database that are near trail

        Args:
            operator_id: onestop operator id
            distance: distance to trail in meters
        """
        url = 'https://transit.land/api/v1/stops'
        params = {'served_by': operator_id, 'per_page': 10000}
        r = requests.get(url, params=params)
        d = r.json()

        stops_near_trail = []
        for stop in d['stops']:
            point = shape(stop['geometry'])
            nearest_trail_point = trail_line.interpolate(
                trail_line.project(point))

            dist = haversine(
                *point.coords, *nearest_trail_point.coords, unit='m')
            if dist < distance:
                stop['distance_to_trail'] = dist
                stops_near_trail.append(stop)

        return stops_near_trail

    def get_routes_for_stop(self, stop):
        for route_serving_stop in stop['routes_serving_stop']:
            route_onestop_id = route_serving_stop['route_onestop_id']
            url = f'https://transit.land/api/v1/onestop_id/{route_onestop_id}'
            if self.routes.get(route_onestop_id) is None:
                r = requests.get(url)
                d = r.json()
                self.routes[route_onestop_id] = d
                route_stops = d['stops_served_by_route']

                # Initialize keys in self.stops to fill in later with full stop
                # information
                for route_stop in route_stops:
                    route_stop_id = route_stop['stop_onestop_id']
                    self.all_stops[route_stop_id] = self.all_stops.get(
                        route_stop_id)

    def update_stop_information(self):
        """Update stop information from Transit land

        Stops are initialized by key in `get_routes_for_stop` but have no data.
        Fill in that data here.
        """
        for stop_id, value in self.all_stops.items():
            if value is not None:
                continue

            url = f'https://transit.land/api/v1/onestop_id/{stop_id}'
            r = requests.get(url)
            self.all_stops[stop_id] = r.json()

    def get_schedules(self):
        """Get schedules to add to route and stop data

        TODO figure out the best way to collect and store this
        """
        url = 'https://transit.land/api/v1/schedule_stop_pairs'
        for route_id in self.routes.keys():
            params = {'route_onestop_id': route_id, 'per_page': 10000}
            r = requests.get(url, params=params)
            d = r.json()

    def get_geojson_for_routes(self):
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
        geojson.FeatureCollection(features)
