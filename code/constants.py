VALID_TRAIL_CODES = ['pct']
VALID_TRAIL_SECTIONS = {
    'pct': ['ca_south', 'ca_central', 'ca_north', 'or', 'wa']
}
TRAIL_HM_XW = {
    'ca_south': ['ca_a', 'ca_b', 'ca_c', 'ca_d', 'ca_e'],
    'ca_central': ['ca_f', 'ca_g', 'ca_h', 'ca_i', 'ca_j', 'ca_k'],
    'ca_north': ['ca_l', 'ca_m', 'ca_n', 'ca_o', 'ca_p', 'ca_q', 'ca_r'],
    'or': ['or_b', 'or_c', 'or_d', 'or_e', 'or_f', 'or_g'],
    'wa': ['wa_h', 'wa_i', 'wa_j', 'wa_k', 'wa_l'],
}
# Note, I'm not currently using this, but rather getting towns from HM section
# names
TRAIL_TOWNS_XW = {
    'ca_south': [
        'acton', 'agua_dulce', 'big_bear_lake', 'cabazon', 'cajon_pass',
        'campo', 'hikertown', 'idyllwild', 'julian', 'lake_morena',
        'mount_laguna', 'tehachapi', 'warner_springs', 'wrightwood'
    ],
    'ca_central': [
        'bishop', 'donner_pass', 'independence', 'inyokern',
        'kennedy_meadows_north', 'kernville', 'lake_isabella', 'lone_pine',
        'mammoth_lakes', 'markleeville', 'mojave', 'reds_meadow', 'ridgecrest',
        'south_lake_tahoe', 'truckee', 'tuolumne_meadows', 'vvr',
        'yosemite_village', 'tehachapi'
    ],
    'ca_north': [
        'belden', 'bucks_lake', 'burney', 'burney_falls', 'castella', 'chester',
        'drakesbad', 'dunsmuir', 'etna', 'mount_shasta', 'old_station',
        'seiad_valley', 'sierra_city', 'soda_springs', 'truckee', 'weed',
        'ashland', 'callahans_lodge'
    ],
    'or': [
        'ashland', 'bend', 'callahans_lodge', 'cascade_locks', 'diamond_lake',
        'fish_lake', 'government_camp', 'mazama_village', 'olallie_lake',
        'rim_village', 'sisters', 'timberline'
    ],
    'wa': [
        'cascade_locks', 'leavenworth', 'mazama', 'packwood', 'skykomish',
        'snoqualmie_pass', 'stehekin', 'stevens_pass', 'stevenson',
        'trout_lake', 'white_pass', 'winthrop'
    ],
}

# A mapping from fire names to wikipedia page titles
FIRE_NAME_WIKIPEDIA_XW = {
    'Norse Peak': '2017 Washington wildfires',
    'Eagle Creek': 'Eagle Creek Fire',
    'Indian Creek': 'Eagle Creek Fire',
    'Whitewater': 'Whitewater Fire',
    'White': 'White Fire',
    'Happy Camp Complex': 'Happy Camp Complex Fire',
    'Wallow': 'Wallow Fire',
    'Nash': 'Nash Fire',
    'Powerhouse': 'Powerhouse Fire',
    'Bluecut': 'Blue Cut Fire',
    'Lake': 'Lake Fire',
    'Pilot': 'Pilot Fire',
    'Holcomb': 'Holcomb Fire',
    'Mountain': 'Mountain Fire',
    'Cranston': 'Cranston Fire',
    'Silver': 'Silver Fire',
    'Spruce Lake': 'High Cascades Complex fires',
    'Blanket Creek': 'High Cascades Complex fires',
    'Meadow': 'Meadow Fire',
    'Butte': 'Butte Fire'
}
