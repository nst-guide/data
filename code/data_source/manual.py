import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from geopandas import GeoDataFrame as GDF

from base import DataSource
from halfmile import Halfmile


class Towns(DataSource):
    """Town information

    For now, town boundaries are drawn by hand.
    """
    def __init__(self):
        super(Towns, self).__init__()
        self.save_dir = self.data_dir / 'pct' / 'polygon' / 'bound' / 'town'

    def boundaries(self) -> GDF:
        """Get town boundaries
        """
        files = sorted(self.save_dir.glob('*/*.geojson'))
        return pd.concat([gpd.read_file(f) for f in files], sort=False)

    def associate_to_halfmile_section(self, trail_gdf=None):
        """For each town, find halfmile section that's closest to it
        """
        if trail_gdf is None:
            trail_gdf = Halfmile().trail_full(alternates=True)
        boundary_files = sorted(self.save_dir.glob('*/*.geojson'))

        for boundary_file in boundary_files:
            bound = gpd.read_file(boundary_file)
            tmp = trail_gdf.copy(deep=True)
            tmp['distance'] = trail_gdf.distance(bound.geometry[0])
            min_dist = tmp[tmp['distance'] == tmp['distance'].min()]

            # Deduplicate based on `section`; don't overcount the main trail and
            # a side trail, they have the same section id
            min_dist = min_dist.drop_duplicates('section')

            assert len(min_dist) <= 2, "Boundary has > 2 trails it's closest to"

            # If a town is touching two trail sections (like Belden), then just
            # pick one of them
            bound['section'] = min_dist['section'].iloc[0]
            # NOTE! This will overwrite town id's not sure how to stop that
            with open(boundary_file, 'w') as f:
                f.write(bound.to_json(show_bbox=True, indent=2))

    def _fix_town_ids(self):
        files = sorted(self.save_dir.glob('*/*.geojson'))
        for f in files:
            identifier = Path(f).stem
            name = ' '.join(s.capitalize() for s in identifier.split('_'))
            with open(f) as x:
                d = json.load(x)

            d['features'][0]['id'] = identifier
            d['features'][0]['properties']['id'] = identifier
            d['features'][0]['properties']['name'] = name

            with open(f, 'w') as x:
                json.dump(d, x, indent=2)
