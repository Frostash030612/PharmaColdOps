"""Build the PharmaColdOps knowledge graph in Neo4j (M6 loader).

Sources, per docs/ARCHITECTURE.md M6:

- products / thresholds : ``src/rule_engine/rules_config.json``
- regulation nodes: WHO TRS 961 Annex 9, EU GDP 2013/C 343/01,
  ICH Q1A(R2), HSA GDP Guidance Notes (Singapore). Clause numbers and
  summaries were checked against the official PDFs on 2026-09-10 (each
  Regulation node carries ``source_url`` + ``verified``); ICH clause-level
  wording remains A's W1 verification task.
- SOP nodes: public procedural guidance at DOCUMENT level — CDC Temperature
  Excursion Checklist (May 2014), WHO shake-test validation study,
  EU GDP 1.2 / 9.2. Company-internal SOPs are proprietary and are NOT used
  (decision recorded in docs/ARCHITECTURE.md §6, 2026-09-11).
- facilities           : C's Singapore routing table (M5) —
  ``data/optimisation/singapore/network.json`` node list (1 cold-chain depot
  + 10 public hospitals), loaded verbatim with geocoded coordinates,
  addresses and per-node ``source_url``; ``type`` is derived from C's
  ``role`` (v1 customers are all public hospitals). The same file's 11×11
  OSMnx shortest-path matrix becomes undirected ``CONNECTS`` edges
  (distance/duration + real route geometry per pair) for the frontend to
  draw.
- real shipments       : the only shipment-level dataset in the project —
  Kaggle "Cold Chain Shipment Silent Failure Dataset" (CC0), ~8,000 records
  (``shipment_id``, transit/temp/rh stats, door opens, package/volume,
  anonymised ``carrier_id`` + ``origin_zone``/``dest_zone`` codes). Loaded
  verbatim with NO Facility/Product edges: zone codes do not map onto C's
  Singapore facility vocabulary and linking them would fabricate geography.
  B's data dictionary flags the dataset as suspected synthetic (highly
  regularised fields) — recorded in each node's ``verified``.
- events & decisions   : runtime chain (ExcursionEvent/Disposition/Cause/
  ReshipmentOrder) is written per real ``case_close`` run by
  ``knowledge_graph/writer.py`` (implemented early 2026-09-11, originally
  scheduled W2 9/24), not pre-loaded. ``data/scenarios/scenarios.csv`` is
  an M3 evaluation artifact (AI-drafted, being double-annotated) and is
  deliberately NOT loaded into the graph (2026-09-11: no fabricated nodes)
- root causes          : the 11 real ``excursion_cause`` classes from B's
  root-cause benchmark (ES vaccine-cold-chain). The runtime ``Cause`` label
  (API ``cause_code`` vocabulary) is a separate one and is written per
  ``case_close`` by the writer, not pre-loaded here.

Usage (cold-chain env, compose Neo4j up — ``docker compose up -d`` — from the repo root)::

    python -m src.knowledge_graph.build_graph

The script rebuilds the graph from scratch on every run (project dev
database only). Connections come from ``knowledge_graph.connect``
(``NEO4J_*`` env vars / ``.env`` / compose defaults); schema
constraints from ``knowledge_graph.schema`` are ensured first.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .connect import get_driver
from .schema import ensure_constraints

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPMENTS_PATH = (
    REPO_ROOT / "data" / "ml" / "cold-chain-silent-failure" / "shipment-sensor-dataset.csv"
)
SHIPMENTS_SOURCE_URL = (
    "https://www.kaggle.com/datasets/skarin/cold-chain-shipment-silent-failure-dataset"
)
NETWORK_PATH = REPO_ROOT / "data" / "optimisation" / "singapore" / "network.json"

# ---------------------------------------------------------------------------
# Static domain content
# ---------------------------------------------------------------------------

REGULATIONS = [
    {
        "clause_id": "R-WHO-TRS961-FREEZE",
        "title": "WHO TRS 961 Annex 9",
        "issuer": "World Health Organization",
        "clause": "§6.9 Shipping container packing — freeze protection",
        "summary": "Pack containers so freeze-sensitive products are protected against temperatures below 0 °C when frozen packs are used.",
        "source_url": "https://cdn.who.int/media/docs/default-source/medicines/norms-and-standards/guidelines/inspections/trs961-annex9-modelguidanceforstoragetransport.pdf",
        "verified": "2026-09-10 official PDF, verbatim match (§6.9)",
    },
    {
        "clause_id": "R-WHO-TRS961-EXCURSION",
        "title": "WHO TRS 961 Annex 9",
        "issuer": "World Health Organization",
        "clause": "§6.2 Product stability profiles",
        "summary": "Excursions above/below the manufacturer's labelled storage range must not adversely affect product quality; product stability data must demonstrate the acceptable excursion time during transport.",
        "source_url": "https://cdn.who.int/media/docs/default-source/medicines/norms-and-standards/guidelines/inspections/trs961-annex9-modelguidanceforstoragetransport.pdf",
        "verified": "2026-09-10 official PDF, verbatim match (§6.2)",
    },
    {
        "clause_id": "R-EU-GDP-1.2",
        "title": "EU GDP 2013/C 343/01",
        "issuer": "European Commission",
        "clause": "Chapter 1.2 — Quality system (deviations & CAPA)",
        "summary": "Deviations from established procedures must be documented and investigated; corrective and preventive actions (CAPA) are taken in line with quality risk management.",
        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52013XC1123(01)",
        "verified": "2026-09-10 official OJ PDF, verbatim match (1.2)",
    },
    {
        "clause_id": "R-EU-GDP-3.2.1",
        "title": "EU GDP 2013/C 343/01",
        "issuer": "European Commission",
        "clause": "Chapter 3.2.1 — Temperature and environment control",
        "summary": "Storage environment (temperature, light, humidity) must be controlled; temperature mapping before use, monitors placed at the points of greatest fluctuation, re-mapping after significant changes.",
        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52013XC1123(01)",
        "verified": "2026-09-10 official OJ PDF, verbatim match (3.2.1)",
    },
    {
        "clause_id": "R-EU-GDP-9.2",
        "title": "EU GDP 2013/C 343/01",
        "issuer": "European Commission",
        "clause": "Chapter 9.2 — Transportation (excursion reporting)",
        "summary": "Storage conditions must be maintained in transit; a temperature excursion or product damage during transportation must be reported to distributor and recipient, with a procedure for investigating and handling it.",
        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52013XC1123(01)",
        "verified": "2026-09-10 official OJ PDF, verbatim match (9.2)",
    },
    {
        "clause_id": "R-EU-GDP-9.4",
        "title": "EU GDP 2013/C 343/01",
        "issuer": "European Commission",
        "clause": "Chapter 9.4 — Products requiring special conditions",
        "summary": "Temperature-sensitive products must be transported using qualified equipment (thermal packaging, temperature-controlled containers or vehicles) so correct transport conditions are maintained.",
        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52013XC1123(01)",
        "verified": "2026-09-10 official OJ PDF, verbatim match (9.4)",
    },
    {
        "clause_id": "R-HSA-GDP",
        "title": "HSA Guidance Notes on Good Distribution Practice (rev. 15 Dec 2023)",
        "issuer": "Singapore HSA",
        "clause": "GDP standard for therapeutic products",
        "summary": "Singapore's mandatory GDP standard for importers and wholesalers of therapeutic products, aligning storage, transport and temperature-control requirements.",
        "source_url": "https://www.hsa.gov.sg/therapeutic-products/manufacturing-import-wholesale/licence-to-manufacturer-import-or-wholesale/gmp-gdp/",
        "verified": "document title/source confirmed 2026-09-10; clause-level wording pending A's W1 check",
    },
    {
        "clause_id": "R-ICH-Q1A",
        "title": "ICH Q1A(R2)",
        "issuer": "ICH",
        "clause": "Stability testing of new drug substances and products",
        "summary": "Basis for product-specific stability data (storage range, allowable excursion duration, MKT ceiling).",
        "source_url": "https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf",
        "verified": "pending A's W1 clause-level check",
    },
]

# Public procedural guidance at DOCUMENT level. Company-internal SOPs are
# proprietary and publicly unavailable, so none of these are invented
# procedures: every step is quoted from the cited source (same provenance
# discipline as REGULATIONS above). Decision record: ARCHITECTURE.md §6.
SOPS = [
    {
        "sop_id": "SOP-GDP-001",
        "title": "Temperature excursion response",
        "summary": "On out-of-range temperature: check power/unit causes (utility, breakers, door seal, monitor placement) and record all temperatures; label exposed vaccines 'Do NOT Use' and set them apart under appropriate conditions; move vaccines to an alternate storage unit (refrigerated first) after checking its temperature; document the action taken and results; contact the immunization program and the manufacturer; return vaccines determined usable only when the storage unit is stable; dispose of compromised stock per distributor/manufacturer and state medical-waste rules.",
        "source_url": "https://stacks.cdc.gov/view/cdc/142711/cdc_142711_DS1.pdf",
        "verified": "2026-09-11 CDC Temperature Excursion Checklist (May 2014), steps quoted from the official PDF; EU GDP 2013/C 343/01 §9.2 requires a procedure for investigating and handling excursions (verified 2026-09-10)",
    },
    {
        "sop_id": "SOP-GDP-002",
        "title": "Freeze-exposure handling (WHO shake test)",
        "summary": "Protect freeze-sensitive products from temperatures below 0 °C (WHO TRS 961 Annex 9 §6.9). On suspected freezing of an aluminum-adjuvanted vaccine: shake a suspect test vial and a deliberately frozen control vial of the same batch for 10–15 seconds and compare sedimentation side by side; similar or faster sedimentation indicates freeze damage and the batch must be discarded (WHO shake test, validated on 475 vials across 8 freeze-sensitive vaccine types).",
        "source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC2908964/",
        "verified": "2026-09-11 WHO shake-test validation study (PMC2908964) + WHO TRS 961 Annex 9 §6.9 official PDF (verified 2026-09-10)",
    },
    {
        "sop_id": "SOP-GDP-003",
        "title": "Deviation documentation & CAPA",
        "summary": "Document every deviation (temperatures, duration, storage unit, affected inventory) and the actions taken; investigate the deviation and take corrective and preventive actions (CAPA) in line with quality risk management; complete final documentation including prevention measures and the final disposition of affected stock.",
        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52013XC1123(01)",
        "verified": "2026-09-10 EU GDP 2013/C 343/01 Chapter 1.2 official OJ PDF (deviations documented & investigated, CAPA per quality risk management); documentation items per CDC excursion checklist (May 2014)",
    },
]

SOP_IMPLEMENTS = {
    "SOP-GDP-001": ["R-EU-GDP-1.2", "R-EU-GDP-9.2", "R-WHO-TRS961-EXCURSION"],
    "SOP-GDP-002": ["R-WHO-TRS961-FREEZE"],
    "SOP-GDP-003": ["R-EU-GDP-1.2", "R-HSA-GDP"],
}

# All products are subject to the general excursion / storage rules; the
# freeze clause only binds freeze-sensitive ones. Thresholds themselves are
# stability data per ICH Q1A(R2).
PRODUCT_RULES = {
    "common": ["R-WHO-TRS961-EXCURSION", "R-EU-GDP-3.2.1", "R-EU-GDP-9.2", "R-EU-GDP-9.4", "R-ICH-Q1A"],
    "freeze_sensitive": ["R-WHO-TRS961-FREEZE"],
}

# Facilities come from C's Singapore routing table (M5) — the same
# ``network.json`` the solver consumes — so the KG can never drift from the
# routing layer: every ReshipmentOrder destination resolves to a Facility
# node that exists in both. Names, addresses and coordinates are C's
# geocoded output (OSMnx/Nominatim over a real OSM Singapore extract;
# per-node ``source_url`` is C's facilities.json citation). ``type`` is
# derived from C's ``role`` for the warehouse/site split used below
# (C's v1 customers are all public hospitals).


def _facilities_from_network() -> list[dict]:
    with open(NETWORK_PATH, encoding="utf-8") as f:
        net = json.load(f)
    prov = net.get("provenance", {})
    sha = prov.get("extract_sha256", "")[:12]
    generated = net.get("generated_at", "")[:10]
    rows = []
    for n in net["nodes"]:
        rows.append({
            "facility_id": n["facility_id"],
            "name": n["name"],
            "role": n["role"],
            "type": "Warehouse" if n["role"] == "depot" else "Hospital",
            "lat": n["lat"],
            "lon": n["lon"],
            "address": n.get("query", ""),
            "geocoded": n.get("geocoder_display_name", ""),
            "source_url": n.get("source_url", ""),
            "verified": (
                f"network.json {generated}: OSMnx/Nominatim geocoding over OSM Singapore extract "
                f"(sha256 {sha}…), © OpenStreetMap contributors"
            ),
        })
    return rows


FACILITIES = _facilities_from_network()

# Class names = B's root-cause benchmark labels (ES vaccine-cold-chain,
# ``excursion_cause``); keep them verbatim so M4 attribution can be written
# into the graph without renames.
ROOT_CAUSES = [
    {"cause_id": "power_outage", "description": "Mains power interruption at the storage facility or during transport."},
    {"cause_id": "no_monitoring_device", "description": "No temperature monitoring device present at the site."},
    {"cause_id": "equipment_breakdown", "description": "Refrigeration equipment failure (non-thermostat)."},
    {"cause_id": "transport_delay", "description": "Extended dwell or transit time beyond the planned window."},
    {"cause_id": "ice_pack_not_conditioned", "description": "Ice packs not pre-conditioned before packing."},
    {"cause_id": "thermostat_failure", "description": "Thermostat malfunction drove temperature out of range."},
    {"cause_id": "staff_error", "description": "Operational error by staff (loading, settings, handling)."},
    {"cause_id": "door_left_open", "description": "Cold-room or reefer door left open."},
    {"cause_id": "overloading", "description": "Storage unit or vehicle loaded beyond capacity."},
    {"cause_id": "generator_fuel_stockout", "description": "Backup generator ran out of fuel."},
    {"cause_id": "not_applicable", "description": "No excursion detected; dictionary node kept for label completeness (no edges)."},
]

# Engine rule_no -> regulations cited / SOP followed / illustrative root
# cause (real class names; only adverse dispositions get a cause — retest /
# release have no anomaly to explain). Kept in one place so the graph stays
# in lockstep with engine.py. Consumed by the per-case case_close writer
# (knowledge_graph/writer.py, implemented early 2026-09-11, originally
# W2 9/24); scenario pre-load removed 2026-09-11. RULE_TO_CAUSE (B's M4
# class names) is NOT used by the writer — runtime ``Cause`` nodes take the
# API's deterministic ``risk.cause_code``.
RULE_TO_REGULATIONS = {
    1: ["R-WHO-TRS961-FREEZE"],
    2: ["R-EU-GDP-9.2"],
    3: ["R-WHO-TRS961-EXCURSION"],
    4: ["R-WHO-TRS961-EXCURSION", "R-EU-GDP-1.2"],
    5: ["R-EU-GDP-1.2"],
    6: ["R-WHO-TRS961-EXCURSION"],
}
RULE_TO_SOPS = {
    1: ["SOP-GDP-002", "SOP-GDP-003"],
    2: ["SOP-GDP-001", "SOP-GDP-003"],
    3: ["SOP-GDP-001", "SOP-GDP-003"],
    4: ["SOP-GDP-001", "SOP-GDP-003"],
    5: ["SOP-GDP-001", "SOP-GDP-003"],
    6: ["SOP-GDP-001", "SOP-GDP-003"],
}
RULE_TO_CAUSE = {
    1: "thermostat_failure",
    2: "ice_pack_not_conditioned",
    3: "equipment_breakdown",
    4: "transport_delay",
    5: None,
    6: None,
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _num_or_none(v: str):
    """CSV cells come as strings; keep genuinely empty cells as None."""
    v = (v or "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def load_real_shipments(driver) -> None:
    """Load real shipment-level records from the Kaggle silent-failure dataset.

    No edges are created: ``origin_zone`` / ``dest_zone`` / ``carrier_id``
    are anonymised codes that do not map onto C's Singapore facility
    vocabulary (zones 0-5, carriers 0-11); linking them would fabricate
    geography. The ``dataset`` property + ``SHP*`` id prefix keep these
    records distinguishable from any future case shipments written at
    runtime.
    """
    with open(SHIPMENTS_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    shipments = []
    for r in rows:
        shipments.append({
            "shipment_id": r["shipment_id"],
            "transit_days": _num_or_none(r["transit_days"]),
            "door_opens": _num_or_none(r["door_opens"]),
            "temp_mean_c": _num_or_none(r["temp_mean_c"]),
            "temp_max_c": _num_or_none(r["temp_max_c"]),
            "temp_min_c": _num_or_none(r["temp_min_c"]),
            "temp_std_c": _num_or_none(r["temp_std_c"]),
            "temp_recovery_rate": _num_or_none(r["temp_recovery_rate"]),
            "rh_mean": _num_or_none(r["rh_mean"]),
            "rh_std": _num_or_none(r["rh_std"]),
            "rh_max": _num_or_none(r["rh_max"]),
            "package_type": r["package_type"],
            "product_volume_l": _num_or_none(r["product_volume_l"]),
            "fill_ratio": _num_or_none(r["fill_ratio"]),
            "carrier_id": r["carrier_id"],
            "origin_zone": r["origin_zone"],
            "dest_zone": r["dest_zone"],
            "leg_count": _num_or_none(r["leg_count"]),
            "sensor_gap_hours": _num_or_none(r["sensor_gap_hours"]),
            "vibration_index": _num_or_none(r["vibration_index"]),
            "silent_failure": r["silent_failure"].strip() in ("1", "True", "true"),
        })
    driver.execute_query(
        """
        UNWIND $rows AS s
        CREATE (n:Shipment {shipment_id: s.shipment_id, transit_days: s.transit_days,
                            door_opens: s.door_opens, temp_mean_c: s.temp_mean_c,
                            temp_max_c: s.temp_max_c, temp_min_c: s.temp_min_c,
                            temp_std_c: s.temp_std_c, temp_recovery_rate: s.temp_recovery_rate,
                            rh_mean: s.rh_mean, rh_std: s.rh_std, rh_max: s.rh_max,
                            package_type: s.package_type, product_volume_l: s.product_volume_l,
                            fill_ratio: s.fill_ratio, carrier_id: s.carrier_id,
                            origin_zone: s.origin_zone, dest_zone: s.dest_zone,
                            leg_count: s.leg_count, sensor_gap_hours: s.sensor_gap_hours,
                            vibration_index: s.vibration_index, silent_failure: s.silent_failure,
                            dataset: 'kaggle-cold-chain-silent-failure',
                            source_url: $src, verified: $verified})
        """,
        parameters_={
            "rows": shipments,
            "src": SHIPMENTS_SOURCE_URL,
            "verified": (
                "Kaggle Cold Chain Shipment Silent Failure Dataset (CC0), ~8,000 shipment-level "
                "records loaded verbatim 2026-09-11; B data dictionary flags highly regularised "
                "fields (suspected synthetic); zone/carrier codes anonymised"
            ),
        },
    )
    print(f"loaded {len(shipments)} real shipments")


def load_facility_links(driver) -> None:
    """Facility ↔ Facility road links from C's Singapore network (M5).

    The 11×11 OSMnx shortest-path matrix in ``network.json`` becomes
    undirected ``CONNECTS`` edges (``distance_m`` / ``duration_s``) — every
    pair also carries its real route geometry (``geometry`` as a
    JSON-encoded string of ``[lon, lat]`` GeoJSON-order coordinate pairs —
    Neo4j cannot store nested lists as properties; per C's assumptions
    note), so the frontend can draw the exact road path the M5 solver
    used. Every value mirrors network.json verbatim — nothing is computed
    or rounded here.
    """
    net = json.loads(NETWORK_PATH.read_text(encoding="utf-8"))
    nodes = net["nodes"]
    dist = net["matrix"]["distance_m"]
    dur = net["matrix"]["duration_s"]
    legs = net["leg_geometry"]
    id_by_node = {n["node_id"]: n["facility_id"] for n in nodes}
    rows = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            key = f"{i}:{j}"
            rows.append({
                "a": id_by_node[i],
                "b": id_by_node[j],
                "distance_m": dist[i][j],
                "duration_s": dur[i][j],
                "geometry": json.dumps(legs.get(key, [])),
            })
    driver.execute_query(
        """
        UNWIND $rows AS row
        MATCH (a:Facility {facility_id: row.a})
        MATCH (b:Facility {facility_id: row.b})
        MERGE (a)-[r:CONNECTS]-(b)
        SET r.distance_m = row.distance_m, r.duration_s = row.duration_s,
            r.geometry = row.geometry, r.source = 'osmnx-shortest-path-2026-09-10'
        """,
        parameters_={"rows": rows},
    )
    print(f"loaded {len(rows)} facility links (all with route geometry)")


def load_static(driver) -> None:
    """Regulations, SOPs, products, facilities, root causes + their links."""
    driver.execute_query("MATCH (n) DETACH DELETE n")

    driver.execute_query(
        """
        UNWIND $rows AS r
        CREATE (n:Regulation {clause_id: r.clause_id, title: r.title,
                              issuer: r.issuer, clause: r.clause, summary: r.summary,
                              source_url: r.source_url, verified: r.verified})
        """,
        parameters_={"rows": REGULATIONS},
    )
    driver.execute_query(
        """
        UNWIND $rows AS s
        CREATE (n:SOP {sop_id: s.sop_id, title: s.title, summary: s.summary,
                       source_url: s.source_url, verified: s.verified})
        """,
        parameters_={"rows": SOPS},
    )
    for sop_id, clause_ids in SOP_IMPLEMENTS.items():
        driver.execute_query(
            """
            MATCH (s:SOP {sop_id: $sop_id})
            UNWIND $clause_ids AS cid
            MATCH (r:Regulation {clause_id: cid})
            MERGE (s)-[:IMPLEMENTS]->(r)
            """,
            parameters_={"sop_id": sop_id, "clause_ids": clause_ids},
        )
    driver.execute_query(
        """
        UNWIND $rows AS f
        CREATE (n:Facility {facility_id: f.facility_id, name: f.name,
                            role: f.role, type: f.type, lat: f.lat, lon: f.lon,
                            address: f.address, geocoded: f.geocoded,
                            source_url: f.source_url, verified: f.verified})
        """,
        parameters_={"rows": FACILITIES},
    )
    driver.execute_query(
        """
        UNWIND $rows AS c
        CREATE (n:RootCause {cause_id: c.cause_id,
                             description: c.description,
                             note: 'class name verbatim from B root-cause benchmark (ES excursion_cause); runtime Cause (API cause_code) is a separate vocabulary written per case_close'})
        """,
        parameters_={"rows": ROOT_CAUSES},
    )

    # Products straight from the engine's own threshold source, so the graph
    # can never drift from rules_config.json. Per-field provenance (_sources)
    # is loaded verbatim onto each node: real citations where they exist
    # (storage range / freeze sensitivity) and honest "principle-anchored
    # default" notes where no public per-product number exists (allowable
    # duration / MKT threshold). Nothing below is authored in this file —
    # build_graph only mirrors rules_config.json.
    raw = json.loads(
        (REPO_ROOT / "src" / "rule_engine" / "rules_config.json").read_text(encoding="utf-8")
    )
    srcs = raw.get("_sources", {})
    _PROVENANCE_KEYS = (
        "category", "refs", "storage_range", "freeze_sensitive",
        "allowable_duration_min", "mkt_threshold_c",
    )
    products = []
    for p in raw["products"]:
        src = srcs.get(p["product_id"], {})
        extra = {k: v for k, v in src.items() if k not in _PROVENANCE_KEYS}
        products.append(
            {
                "product_id": p["product_id"],
                "storage_min_c": p["storage_min_c"],
                "storage_max_c": p["storage_max_c"],
                "allowable_duration_min": p["allowable_duration_min"],
                "mkt_threshold_c": p["mkt_threshold_c"],
                "retestable": p["retestable"],
                "freeze_sensitive": p["freeze_sensitive"],
                "category": src.get("category", ""),
                "storage_source": src.get("storage_range", ""),
                "freeze_source": src.get("freeze_sensitive", ""),
                "threshold_note": (
                    "allowable_duration_min: " + src.get("allowable_duration_min", "")
                    + " | mkt_threshold_c: " + src.get("mkt_threshold_c", "")
                ),
                "design_notes": json.dumps(extra, ensure_ascii=False) if extra else "",
                "source_urls": src.get("refs", []),
                "rule_ids": PRODUCT_RULES["common"]
                + (PRODUCT_RULES["freeze_sensitive"] if p["freeze_sensitive"] else []),
            }
        )
    driver.execute_query(
        """
        UNWIND $rows AS p
        CREATE (n:Product {product_id: p.product_id, storage_min_c: p.storage_min_c,
                           storage_max_c: p.storage_max_c,
                           allowable_duration_min: p.allowable_duration_min,
                           mkt_threshold_c: p.mkt_threshold_c,
                           retestable: p.retestable, freeze_sensitive: p.freeze_sensitive,
                           category: p.category, storage_source: p.storage_source,
                           freeze_source: p.freeze_source, threshold_note: p.threshold_note,
                           design_notes: p.design_notes, source_urls: p.source_urls})
        FOREACH (rid IN p.rule_ids |
            MERGE (r:Regulation {clause_id: rid})
            MERGE (n)-[:REGULATED_BY]->(r))
        """,
        parameters_={"rows": products},
    )

    # Product → SOP (FOLLOWS_PROCEDURE): derived through the SAME maps the
    # runtime writer uses — a product's governing clauses (rule_ids) appear
    # in rules (RULE_TO_REGULATIONS), those rules follow SOPs
    # (RULE_TO_SOPS). No new data is authored here; static and runtime
    # edges therefore can never disagree.
    clause_to_rules: dict = {}
    for rule_no, clause_ids in RULE_TO_REGULATIONS.items():
        for cid in clause_ids:
            clause_to_rules.setdefault(cid, set()).add(rule_no)
    product_sops = []
    for p in products:
        rules = set().union(*(clause_to_rules.get(cid, set()) for cid in p["rule_ids"]))
        sops = sorted({sid for r in rules for sid in RULE_TO_SOPS.get(r, [])})
        product_sops.append({"product_id": p["product_id"], "sop_ids": sops})
    driver.execute_query(
        """
        UNWIND $rows AS row
        MATCH (p:Product {product_id: row.product_id})
        FOREACH (sid IN row.sop_ids |
            MERGE (s:SOP {sop_id: sid})
            MERGE (p)-[:FOLLOWS_PROCEDURE]->(s))
        """,
        parameters_={"rows": product_sops},
    )


# NOTE (2026-09-11): the scenario pre-load (57 AI-drafted rows from
# data/scenarios/scenarios.csv) has been REMOVED from the graph — those are
# fabricated events made for an early frontend demo and must not appear as
# evidence. scenarios.csv stays on disk as M3's annotation/evaluation
# artifact (proposal §8.3, being double-annotated), it is just not loaded
# into Neo4j. The runtime chain (ExcursionEvent/Disposition/Cause/
# ReshipmentOrder) enters the graph per real ``case_close`` run via
# knowledge_graph/writer.py (implemented early 2026-09-11, originally
# W2 9/24), which uses RULE_TO_REGULATIONS / RULE_TO_SOPS below.


def main() -> None:
    driver = get_driver()
    try:
        ensure_constraints(driver)
        load_static(driver)
        load_facility_links(driver)
        load_real_shipments(driver)
        counts = driver.execute_query(
            """
            MATCH (n) RETURN labels(n) AS label, count(n) AS n
            ORDER BY label
            """
        ).records
        edge_counts = driver.execute_query(
            """
            MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS n ORDER BY t
            """
        ).records
        print("node counts:", {r["label"][0]: r["n"] for r in counts})
        print("edge counts:", {r["t"]: r["n"] for r in edge_counts})
    finally:
        driver.close()


if __name__ == "__main__":
    main()
