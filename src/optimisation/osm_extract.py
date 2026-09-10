"""Filter a local OSM XML extract into public drive ways for OSMnx.

The tag exclusions mirror OSMnx 2.1's drive profile. OSMnx still handles
one-way direction, topology and simplification. Two streaming passes avoid
loading buildings, land use and unrelated nodes into the routing graph.
"""
from __future__ import annotations

import gzip
from pathlib import Path
import re
import xml.etree.ElementTree as ET

EXCLUDED_HIGHWAYS = re.compile(
    'abandoned|bridleway|bus_guideway|construction|corridor|cycleway|elevator|'
    'escalator|footway|no|path|pedestrian|planned|platform|proposed|raceway|'
    'razed|rest_area|service|services|steps|track'
)
EXCLUDED_SERVICES = re.compile('alley|driveway|emergency_access|parking|parking_aisle|private')


def is_drive_way(tags: dict[str, str]) -> bool:
    return bool(tags.get('highway')) and not any((
        EXCLUDED_HIGHWAYS.search(tags.get('highway', '')),
        EXCLUDED_SERVICES.search(tags.get('service', '')),
        'yes' in tags.get('area', ''),
        'private' in tags.get('access', ''),
        'no' in tags.get('motor_vehicle', ''),
        'no' in tags.get('motorcar', ''),
    ))


def _elements(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        parser = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(parser)
        for event, elem in parser:
            if event == 'end' and elem.tag in ('node', 'way', 'relation'):
                yield elem
                elem.clear()
                root.clear()


def filter_drive_xml(source: Path, destination: Path) -> dict:
    """Write only drivable ways and their nodes, preserving original OSM tags."""
    node_ids = set()
    ways = []
    for elem in _elements(source):
        if elem.tag == 'way':
            tags = {t.attrib['k']: t.attrib['v'] for t in elem.findall('tag')}
            if is_drive_way(tags):
                ways.append(ET.tostring(elem, encoding='utf-8'))
                node_ids.update(n.attrib['ref'] for n in elem.findall('nd'))
    if not ways:
        raise ValueError(f'{source}: no drive ways in extract')
    temporary = destination.with_suffix('.tmp')
    found = set()
    with temporary.open('wb') as out:
        out.write(b'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6" generator="PharmaColdOps-drive-filter">\n')
        for elem in _elements(source):
            if elem.tag == 'node' and elem.attrib['id'] in node_ids:
                found.add(elem.attrib['id'])
                out.write(ET.tostring(elem, encoding='utf-8'))
        for way in ways:
            out.write(way)
        out.write(b'</osm>\n')
    if node_ids - found:
        temporary.unlink()
        raise ValueError(f'{source}: {len(node_ids-found)} referenced road nodes missing')
    temporary.replace(destination)
    return {'drive_ways': len(ways), 'drive_nodes': len(found)}
