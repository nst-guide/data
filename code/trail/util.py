from typing import Optional

import data_source
from constants import VALID_TRAIL_CODES, VALID_TRAIL_SECTIONS
from constants.pct import TRAIL_HM_XW


def approx_trail(
        trail_code: str,
        trail_section: Optional[str] = None,
        alternates: bool = True):
    """Retrieve approximate trail geometry

    There are many instances when I need an _approximate_ trail geometry. First
    and foremost, I use the approximate trail line to generate the polygons
    within which to download OSM data! It takes _forever_ to download the entire
    PCT relation through the OSM api, because you have to recursively download
    relations -> way -> nodes, and so make tens of thousands of http requests.

    (This function isn't currently used for downloading OSM; that's hardcoded,
    but it can be refactored in the future.)

    Otherwise, also helpful for:

    - getting wikipedia articles near the trail
    - transit near the trail

    Args:
        - trail_code: the code for the trail of interest, i.e. 'pct'
        - trail_section: the code for the trail section of interest, i.e.
          'ca_south'. If None, returns the entire trail.
        - alternates: if True, includes alternates

    Returns:
        GeoDataFrame representing trail
    """
    if trail_code not in VALID_TRAIL_CODES:
        msg = f'Invalid trail_code. Valid values are: {VALID_TRAIL_CODES}'
        raise ValueError(msg)

    if trail_section is not None:
        if trail_section not in VALID_TRAIL_SECTIONS.get(trail_code):
            msg = f'Invalid trail_section. Valid values are: {VALID_TRAIL_SECTIONS}'
            raise ValueError(msg)

    if trail_code == 'pct':
        hm = data_source.Halfmile()
        if trail_section is None:
            return hm.trail_full(alternates=alternates)

        hm_sections = TRAIL_HM_XW.get(trail_section)
        return hm.trail_section(hm_sections, alternates=alternates)
    else:
        raise NotImplementedError
