import geojson


def osm_poly_to_geojson(lines):
    lines = [line.rstrip() for line in lines]
    # name = lines[0]

    section_starts = [
        ind for ind, line in enumerate(lines) if line[:3] not in ['   ', 'END']
    ]
    section_ends = [ind for ind, line in enumerate(lines) if line[:3] == 'END']

    features = []
    for start, end in zip(section_starts, section_ends):
        part = lines[start:end]
        section_name = part[0]
        coords = [line.split() for line in part[1:]]

        # Convert str to float
        # the float() function handles the scientific notation
        coords = [(float(coord[0]), float(coord[1])) for coord in coords]

        polygon = geojson.Polygon(coordinates=coords)
        feature = geojson.Feature(
            geometry=polygon, properties={'name': section_name})
        features.append(feature)

    feature_collection = geojson.FeatureCollection(features)
    return feature_collection


def multipolygon_to_osm_poly(multipolygon):
    """Generate OSM .poly file from Shapely MultiPolygon"""
    lines = ['poly_name']
    section_counter = 1
    for polygon in multipolygon:
        lines.append(str(section_counter))
        section_counter += 1

        for coord in polygon.exterior.coords:
            lines.append(f'    {coord[0]}    {coord[1]}')

        lines.append('END')

    lines.append('END')
    return '\n'.join(lines)


def coords_to_osm_poly(coords):
    lines = [
        'poly_name',
        'first_area',
    ]
    for coord in coords:
        lines.append(f'    {coord[0]}    {coord[1]}')
    lines.append('END')
    lines.append('END')
    return '\n'.join(lines)
