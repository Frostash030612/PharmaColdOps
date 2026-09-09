"""Build the PharmaColdOps knowledge graph in Neo4j (M6 loader).

Sources, per docs/ARCHITECTURE.md M6:

- products / thresholds : ``src/rule_engine/rules_config.json``
- regulation & SOP nodes: WHO TRS 961 Annex 9, EU GDP 2013/C 343/01,
  ICH Q1A(R2), PIC/S PI 041-1 (adopted by Singapore HSA)
- facilities           : Singapore cold-chain warehouses, public hospitals,
  polyclinics and pharmacies (OSM coordinate approximations)
- events & decisions   : ``data/scenarios/scenarios.csv`` run through the real
  RuleEngine, so every Decision node mirrors an auditable engine output
  (rule_no, reason, regulation) and the engine's reshipment flag becomes a
  ReshipmentOrder node (M5's input contract)
- root causes          : the 11 real ``excursion_cause`` classes from B's
  root-cause benchmark (ES vaccine-cold-chain). Scenario→cause edges are
  illustrative until B's model attributes causes to live events (W3).

Usage (cold-chain env, ``pharmaneo`` container running, from the repo root)::

    python -m src.knowledge_graph.build_graph

The script rebuilds the graph from scratch on every run (project dev
database only). Connection defaults: ``NEO4J_URI`` / ``NEO4J_USER`` /
``NEO4J_PASSWORD`` environment variables.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from neo4j import GraphDatabase

from src.rule_engine.engine import RuleEngine
from src.rule_engine.models import Disposition, ExcursionEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = REPO_ROOT / "data" / "scenarios" / "scenarios.csv"

URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "pharmacoldops")

# ---------------------------------------------------------------------------
# Static domain content
# ---------------------------------------------------------------------------

REGULATIONS = [
    {
        "clause_id": "R-WHO-TRS961-FREEZE",
        "title": "WHO TRS 961 Annex 9",
        "issuer": "World Health Organization",
        "clause": "Freeze damage of vaccines",
        "summary": "Freeze-sensitive vaccines lose potency when frozen; exposure at or below the freezing point requires discard.",
    },
    {
        "clause_id": "R-WHO-TRS961-EXCURSION",
        "title": "WHO TRS 961 Annex 9",
        "issuer": "World Health Organization",
        "clause": "Allowable temperature excursion and MKT limits",
        "summary": "Excursions beyond the product stability margin (duration or MKT) require hold and quality assessment.",
    },
    {
        "clause_id": "R-EU-GDP-9.4",
        "title": "EU GDP 2013/C 343/01",
        "issuer": "European Commission",
        "clause": "Chapter 9.4 — transport deviation handling",
        "summary": "Temperature deviations during transport must be recorded and assessed; the batch is held until the quality impact is resolved.",
    },
    {
        "clause_id": "R-EU-GDP-3.2.2",
        "title": "EU GDP 2013/C 343/01",
        "issuer": "European Commission",
        "clause": "Chapter 3.2.2 — storage temperature deviations",
        "summary": "Storage and transport must keep products within labelled conditions; deviations trigger investigation and disposition.",
    },
    {
        "clause_id": "R-ICH-Q1A",
        "title": "ICH Q1A(R2)",
        "issuer": "ICH",
        "clause": "Stability testing of new drug substances and products",
        "summary": "Basis for product-specific stability data (storage range, allowable excursion duration, MKT ceiling).",
    },
    {
        "clause_id": "R-PICS-PI041",
        "title": "PIC/S PI 041-1",
        "issuer": "PIC/S (adopted by Singapore HSA)",
        "clause": "Good distribution practices for medicinal products",
        "summary": "GDP reference adopted in Singapore; aligns storage, transport and deviation-management requirements.",
    },
]

SOPS = [
    {
        "sop_id": "SOP-GDP-001",
        "title": "Temperature deviation handling & release assessment",
        "summary": "Assess excursion severity, decide hold / test / release, document the justification.",
    },
    {
        "sop_id": "SOP-GDP-002",
        "title": "Freeze-exposure discard",
        "summary": "Discard freeze-sensitive product exposed below the freezing point; record as waste with root cause.",
    },
    {
        "sop_id": "SOP-GDP-003",
        "title": "Deviation logging & audit trail",
        "summary": "Log every deviation, decision and citation so the audit chain stays traceable.",
    },
]

SOP_IMPLEMENTS = {
    "SOP-GDP-001": ["R-EU-GDP-9.4", "R-EU-GDP-3.2.2", "R-WHO-TRS961-EXCURSION"],
    "SOP-GDP-002": ["R-WHO-TRS961-FREEZE"],
    "SOP-GDP-003": ["R-EU-GDP-9.4", "R-PICS-PI041"],
}

# All products are subject to the general excursion / storage rules; the
# freeze clause only binds freeze-sensitive ones. Thresholds themselves are
# stability data per ICH Q1A(R2).
PRODUCT_RULES = {
    "common": ["R-WHO-TRS961-EXCURSION", "R-EU-GDP-3.2.2", "R-ICH-Q1A"],
    "freeze_sensitive": ["R-WHO-TRS961-FREEZE"],
}

FACILITIES = [
    {"facility_id": "W-TUAS", "name": "Tuas Cold Chain Hub", "type": "Warehouse", "lat": 1.320, "lon": 103.650},
    {"facility_id": "W-JURONG", "name": "Jurong Logistics Terminal", "type": "Warehouse", "lat": 1.330, "lon": 103.720},
    {"facility_id": "W-CHANGI", "name": "Changi Airfreight Cold Zone", "type": "Warehouse", "lat": 1.360, "lon": 103.990},
    {"facility_id": "H-SGH", "name": "Singapore General Hospital", "type": "Hospital", "lat": 1.2807, "lon": 103.8343},
    {"facility_id": "H-NUH", "name": "National University Hospital", "type": "Hospital", "lat": 1.2938, "lon": 103.7838},
    {"facility_id": "H-KKH", "name": "KK Women's and Children's Hospital", "type": "Hospital", "lat": 1.3094, "lon": 103.8492},
    {"facility_id": "H-TTSH", "name": "Tan Tock Seng Hospital", "type": "Hospital", "lat": 1.3197, "lon": 103.8465},
    {"facility_id": "H-CGH", "name": "Changi General Hospital", "type": "Hospital", "lat": 1.3404, "lon": 103.9498},
    {"facility_id": "P-OUTRAM", "name": "SingHealth Polyclinic (Outram)", "type": "Polyclinic", "lat": 1.2789, "lon": 103.8398},
    {"facility_id": "PH-GUARDIAN", "name": "Guardian Pharmacy (Raffles City)", "type": "Pharmacy", "lat": 1.2940, "lon": 103.8533},
    {"facility_id": "PH-UNITY", "name": "Unity Pharmacy (Toa Payoh HDB Hub)", "type": "Pharmacy", "lat": 1.3340, "lon": 103.8500},
]

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
# in lockstep with engine.py.
RULE_TO_REGULATIONS = {
    1: ["R-WHO-TRS961-FREEZE"],
    2: ["R-EU-GDP-9.4"],
    3: ["R-WHO-TRS961-EXCURSION"],
    4: ["R-WHO-TRS961-EXCURSION", "R-EU-GDP-9.4"],
    5: ["R-EU-GDP-9.4"],
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

def load_static(driver) -> None:
    """Regulations, SOPs, products, facilities, root causes + their links."""
    driver.execute_query("MATCH (n) DETACH DELETE n")

    driver.execute_query(
        """
        UNWIND $rows AS r
        CREATE (n:Regulation {clause_id: r.clause_id, title: r.title,
                              issuer: r.issuer, clause: r.clause, summary: r.summary})
        """,
        parameters_={"rows": REGULATIONS},
    )
    driver.execute_query(
        """
        UNWIND $rows AS s
        CREATE (n:SOP {sop_id: s.sop_id, title: s.title, summary: s.summary})
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
                            type: f.type, lat: f.lat, lon: f.lon})
        """,
        parameters_={"rows": FACILITIES},
    )
    driver.execute_query(
        """
        UNWIND $rows AS c
        CREATE (n:RootCause {cause_id: c.cause_id,
                             description: c.description,
                             note: 'class name verbatim from B root-cause benchmark (ES excursion_cause); scenario edges illustrative until M4 attribution (W3)'})
        """,
        parameters_={"rows": ROOT_CAUSES},
    )

    # Products straight from the engine's own threshold source, so the graph
    # can never drift from rules_config.json.
    raw = json.loads(
        (REPO_ROOT / "src" / "rule_engine" / "rules_config.json").read_text(encoding="utf-8")
    )
    products = []
    for p in raw["products"]:
        products.append(
            {
                "product_id": p["product_id"],
                "storage_min_c": p["storage_min_c"],
                "storage_max_c": p["storage_max_c"],
                "allowable_duration_min": p["allowable_duration_min"],
                "mkt_threshold_c": p["mkt_threshold_c"],
                "retestable": p["retestable"],
                "freeze_sensitive": p["freeze_sensitive"],
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
                           retestable: p.retestable, freeze_sensitive: p.freeze_sensitive})
        FOREACH (rid IN p.rule_ids |
            MERGE (r:Regulation {clause_id: rid})
            MERGE (n)-[:REGULATED_BY]->(r))
        """,
        parameters_={"rows": products},
    )


def load_scenarios(driver) -> None:
    """Run every scenario through the real engine and write the decision chain."""
    engine = RuleEngine()
    warehouses = [f["facility_id"] for f in FACILITIES if f["type"] == "Warehouse"]
    sites = [f["facility_id"] for f in FACILITIES if f["type"] != "Warehouse"]

    with open(SCENARIOS_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for i, row in enumerate(rows):
        event = ExcursionEvent(
            scenario_id=row["scenario_id"],
            product_id=row["product_id"],
            excursion_temp_c=float(row["excursion_temp_c"]),
            duration_min=int(row["duration_min"]),
            mkt_c=float(row["mkt_c"]),
            packaging=row["packaging"],
            stage=row["stage"],
        )
        decision = engine.evaluate(event)
        reg_ids = RULE_TO_REGULATIONS[decision.rule_no]
        # Only adverse dispositions violate a clause; release/retest merely
        # cite the governing text.
        violates = reg_ids if decision.disposition in (Disposition.SCRAP, Disposition.QUARANTINE) else []
        cause_id = RULE_TO_CAUSE[decision.rule_no]

        origin = warehouses[i % len(warehouses)]
        dest = sites[i % len(sites)]
        driver.execute_query(
            """
            MERGE (s:Shipment {shipment_id: $shipment_id})
            SET s.stage = $stage
            MERGE (o:Facility {facility_id: $origin})
            MERGE (d:Facility {facility_id: $dest})
            MERGE (p:Product {product_id: $product_id})
            MERGE (s)-[:DEPARTS_FROM]->(o)
            MERGE (s)-[:DELIVERS_TO]->(d)
            MERGE (s)-[:CARRIES]->(p)
            CREATE (e:ExcursionEvent {scenario_id: $scenario_id, product_id: $product_id,
                                      excursion_temp_c: $temp, duration_min: $dur,
                                      mkt_c: $mkt, packaging: $packaging, stage: $stage,
                                      gold_label: $gold})
            CREATE (e)-[:OCCURRED_ON]->(s)
            CREATE (dec:Decision {scenario_id: $scenario_id, disposition: $disp,
                                  reshipment_required: $reship, rule_no: $rule_no,
                                  reason: $reason, regulation: $regulation,
                                  rule_path: $rule_path})
            CREATE (dec)-[:RESOLVES]->(e)
            FOREACH (rid IN $reg_ids |
                MERGE (r:Regulation {clause_id: rid})
                MERGE (dec)-[:CITES]->(r))
            FOREACH (rid IN $violates |
                MERGE (r:Regulation {clause_id: rid})
                MERGE (e)-[:VIOLATES]->(r))
            FOREACH (sid IN $sop_ids |
                MERGE (sp:SOP {sop_id: sid})
                MERGE (dec)-[:FOLLOWS]->(sp))
            """,
            parameters_={
                "shipment_id": f"SHIP-{row['scenario_id']}",
                "stage": row["stage"],
                "origin": origin,
                "dest": dest,
                "product_id": row["product_id"],
                "scenario_id": row["scenario_id"],
                "temp": event.excursion_temp_c,
                "dur": event.duration_min,
                "mkt": event.mkt_c,
                "packaging": event.packaging,
                "gold": row["gold_label"],
                "disp": decision.disposition.value,
                "reship": decision.reshipment_required,
                "rule_no": decision.rule_no,
                "reason": decision.reason,
                "regulation": decision.regulation,
                "rule_path": decision.rule_path,
                "reg_ids": reg_ids,
                "violates": violates,
                "sop_ids": RULE_TO_SOPS[decision.rule_no],
            },
        )
        if cause_id:
            driver.execute_query(
                """
                MATCH (e:ExcursionEvent {scenario_id: $scenario_id})
                MERGE (c:RootCause {cause_id: $cause_id})
                MERGE (c)-[:CAUSED]->(e)
                """,
                parameters_={"scenario_id": row["scenario_id"], "cause_id": cause_id},
            )
        if decision.reshipment_required:
            driver.execute_query(
                """
                MATCH (dec:Decision {scenario_id: $scenario_id})
                MATCH (d:Facility {facility_id: $dest})
                CREATE (ro:ReshipmentOrder {order_id: $order_id, product_id: $product_id,
                                            destination: $dest})
                CREATE (dec)-[:TRIGGERS]->(ro)
                CREATE (ro)-[:DELIVERS_TO]->(d)
                """,
                parameters_={
                    "scenario_id": row["scenario_id"],
                    "order_id": f"RO-{row['scenario_id']}",
                    "product_id": row["product_id"],
                    "dest": dest,
                },
            )
    print(f"loaded {len(rows)} scenarios")


def main() -> None:
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        driver.verify_connectivity()
        load_static(driver)
        load_scenarios(driver)
        counts = driver.execute_query(
            """
            MATCH (n) RETURN labels(n) AS label, count(n) AS n
            ORDER BY label
            """
        ).records
        print("node counts:", {r["label"][0]: r["n"] for r in counts})
    finally:
        driver.close()


if __name__ == "__main__":
    main()
