"""Demo end-of-day parking: warehouses only, never receiving hospitals."""
WAREHOUSE_ROLES = {"depot", "distribution", "third_party"}


def warehouse_ids(network):
    return tuple(n["facility_id"] for n in network["nodes"] if n["role"] in WAREHOUSE_ROLES)


def validate_terminals(network, terminals):
    nodes = {n["facility_id"]: n for n in network["nodes"]}
    unknown = set(terminals or ()) - nodes.keys()
    if unknown:
        raise ValueError(f"unknown terminal facilities: {sorted(unknown)}")
    forbidden = set(terminals or ()) - set(warehouse_ids(network))
    if forbidden:
        raise ValueError(f"end-of-day parking must be at warehouses, not hospitals: {sorted(forbidden)}")


def validate_end_node(network, node_id):
    node = next((n for n in network["nodes"] if n["node_id"] == node_id), None)
    if node is None or node["role"] not in WAREHOUSE_ROLES:
        raise ValueError("end-of-day parking must be at a warehouse; select allowed warehouse terminals")
