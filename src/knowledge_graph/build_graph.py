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
  ``role`` (v1 customers are all public hospitals)
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
NETWORK_PATH = REPO_ROOT / "data" / "optimisation" / "singapore" / "network.json"


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
# in lockstep with engine.py.
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
                             note: 'class name verbatim from B root-cause benchmark (ES excursion_cause); scenario edges illustrative until M4 attribution (W3)'})
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
