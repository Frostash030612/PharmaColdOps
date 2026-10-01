"""Reproducible ASGI/API acceptance in a new, isolated directory.

Only wall time is controlled: every business mutation goes through the API.
No SQL/state/route injection, no fake successful graph writes. Use --graph to
include a configured, already seeded Neo4j in the acceptance.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient
from api import service
from api.main import app
from optimisation import tracking
from optimisation.parking_policy import warehouse_ids
from optimisation.singapore_loader import read_network
from optimisation.singapore_export import sequence_distance_m

SEED = 41
DAY = "2026-10-01"


class DemoTime(datetime.datetime):
    instant = datetime.datetime(2026, 10, 1, 9)

    @classmethod
    def now(cls, tz=None):
        return cls.instant if tz is None else cls.instant.replace(tzinfo=tz)


class Acceptance:
    def __init__(self, client):
        self.client = client
        self.checks = []
        self.snapshots = {}

    def check(self, name, condition):
        if not condition:
            raise AssertionError(name)
        self.checks.append(name)

    def call(self, method, path, body=None, status=200):
        response = self.client.request(method, path, json=body)
        if response.status_code != status:
            raise AssertionError(f"{method} {path}: {response.status_code}: {response.text}")
        return response.json()

    def post(self, path, body=None, status=200):
        return self.call("POST", path, body or {}, status)

    def get(self, path):
        return self.call("GET", path)

    def run(self, dispatch_id):
        return self.get(f"/api/dispatch/runs/{dispatch_id}")

    def settle(self, dispatch_id, predicate):
        self.post(f"/api/dispatch/runs/{dispatch_id}/speed", {"speed": 300})
        for _ in range(8):
            DemoTime.instant += datetime.timedelta(seconds=30)
            body = self.post(f"/api/dispatch/runs/{dispatch_id}/tick")
            if predicate(body):
                self.post(f"/api/dispatch/runs/{dispatch_id}/speed", {"speed": 0})
                return self.run(dispatch_id)
        raise AssertionError(f"{dispatch_id} did not settle through real tick logic")

    def legal_routes(self, body):
        network = read_network()
        warehouses = set(warehouse_ids(network))
        for route in body["route_view"]["routes"]:
            if route.get("status") == "failed":
                continue
            self.check("route ends at an allowed warehouse",
                network["nodes"][route["end_node_id"]]["facility_id"] in
                set(body["input"]["constraints"]["terminal_facility_ids"]) <= warehouses)
            driven = sum(sequence_distance_m(network, [leg["from"], leg["to"]]) for leg in route["legs"])
            self.check("route legs and displayed distance agree", abs(route["total_distance"] * 1000 - driven) < 6)

    def main_day(self):
        config = {"scenario": "routine", "seed": SEED, "operating_date": DAY,
            "order_count": 4, "product_ids": ["vaccine_2_8"],
            "origin_facility_ids": ["W-WESTGATE"], "quantity_min": 10,
            "quantity_max": 10, "window_min": 480, "window_max": 480,
            "fleet_size": 3, "spare_quantity": 20}
        generated = self.post("/api/dispatch/simulated-orders", config)
        self.check("seed/config/source hashes reproduce the same batch",
            generated == self.post("/api/dispatch/simulated-orders", config))
        plan = generated["plan"]
        plan["constraints"].update(max_stops_per_vehicle=8, max_vehicles=3,
            mileage_limit_m=150000, terminal_facility_ids=["D-NORTHPOINT", "D-HOUGANG"])
        preview = self.post("/api/dispatch/plan", plan)
        self.check("ordinary plan is feasible", preview["feasible"])
        did = "PLAN-DEMO-DAY1"
        created = self.post("/api/dispatch/runs", {**plan, "dispatch_id": did, "command_id": "demo-create"})
        self.legal_routes(created)
        urgent = {"request_id": "demo-urgent", "product_id": "vaccine_2_8",
            "origin_facility_id": "W-WESTGATE", "destination_facility_id": "H-NUH", "latest_min": 1020}
        branch = self.post(f"/api/dispatch/runs/{did}/urgent-preview", urgent)
        self.check("urgent preview does not change state", self.run(did)["version"] == created["version"])
        candidate = next(c for c in branch["candidates"] if c["feasible"] and c["kind"] == "load_before_departure")
        command = {**urgent, "expected_version": branch["state_version"], "command_id": "demo-accept-urgent",
            "candidate_kind": candidate["kind"], "vehicle_id": candidate["vehicle_id"]}
        accepted = self.post(f"/api/dispatch/runs/{did}/urgent-accept", command)
        duplicate = self.post(f"/api/dispatch/runs/{did}/urgent-accept", command)
        self.check("urgent retry is idempotent", accepted["version"] == duplicate["version"])
        self.check("urgent input has no business cargo quantity", "quantity" not in urgent)
        self.post(f"/api/dispatch/runs/{did}/depart", {"command_id": "demo-depart", "speed": 0})
        self.post(f"/api/dispatch/runs/{did}/overnight-preview", status=409)
        order = plan["orders"][0]
        event = {"registration_id": "demo-incident", "started_at": DAY + "T09:00:00",
            "product_id": order["product_id"], "order_id": order["order_id"], "dispatch_id": did,
            "destination_facility_id": order["destination_facility_id"], "facility_id": "W-WESTGATE",
            "excursion_temp_c": 20, "duration_min": 90, "mkt_c": 19,
            "packaging": "intact", "stage": "transit", "remark": "simulated loading checkpoint excursion"}
        case = self.post("/api/case_close", event)
        rid = case["run_id"]
        self.check("lost-response retry retains original assessment", self.post("/api/case_close", event)["run_id"] == rid)
        self.check("incident preserves active order and event facility", case["linked_order"]["order_id"] == order["order_id"]
            and case["event"]["facility_id"] == "W-WESTGATE" and case["reshipment_required"])
        self.post(f"/api/runs/{rid}/workflow", {"status": "closed", "expected_version": 0}, status=409)
        replacement = self.post("/api/dispatch/reshipments/preview", {"run_id": rid})
        candidate = next(c for c in replacement["candidates"] if c["feasible"])
        rescued = self.post("/api/dispatch/reshipments", {"run_id": rid,
            "candidate_kind": candidate["kind"], "vehicle_id": candidate["vehicle_id"]})
        self.check("replacement belongs to the original operation", rescued["dispatch_id"] == did)
        completed = self.settle(did, lambda b: b["status"] == "completed" and b["route_view"]["metrics"]["still_returning"] == 0)
        self.legal_routes(completed)
        self.check("quality replacement was actually delivered", completed["orders"][f"RO-{rid}"]["status"] == "delivered")
        history = self.get("/api/runs")["runs"]
        handled = next(c for c in history if c["run_id"] == rid)
        self.check("quality workflow advances only after delivery", handled["processing_status"] == "handled")
        closed = self.post(f"/api/runs/{rid}/workflow", {"status": "closed",
            "expected_version": handled["workflow_version"], "remark": "replacement signed; quality action reviewed (demo)"})
        self.check("operator closure is persistent", closed["processing_status"] == "closed")
        # Force a legal nonzero closing move, not an already parked no-op.
        target = "D-HOUGANG" if next(iter(completed["vehicles"].values()))["current_facility_id"] == "D-NORTHPOINT" else "D-NORTHPOINT"
        parking = {"demo_replenish": True, "parking_overrides": {v: target for v in completed["vehicles"]}}
        park = self.post(f"/api/dispatch/runs/{did}/overnight-preview", parking)
        self.check("overnight plan feasible with demo supply", park["feasible"])
        park_command = {**parking, "expected_version": park["state_version"], "command_id": "demo-park"}
        moving = self.post(f"/api/dispatch/runs/{did}/overnight-accept", park_command)
        self.check("parking confirmation cannot teleport trucks", moving["overnight"]["status"] == "repositioning")
        self.check("parking retry is idempotent", self.post(f"/api/dispatch/runs/{did}/overnight-accept", park_command)["version"] == moving["version"])
        next_command = {"dispatch_id": "PLAN-DEMO-DAY2", "command_id": "demo-next-day",
            "expected_version": moving["version"], "depart": False, "speed": 0}
        self.post(f"/api/dispatch/runs/{did}/next-day", next_command, status=409)
        parked = self.settle(did, lambda b: b["overnight"]["status"] == "parked")
        next_command["expected_version"] = parked["version"]
        tomorrow = self.post(f"/api/dispatch/runs/{did}/next-day", next_command)
        self.check("next date and actual parked starts are inherited", tomorrow["operating_date"] == "2026-10-02"
            and all(v["start_facility_id"] == target for v in tomorrow["vehicles"].values()))
        self.check("temporary urgent/reshipment not copied to daily fixed batch",
            {o["order_id"] for o in tomorrow["input"]["orders"]} == {o["order_id"] for o in plan["orders"]})
        self.check("new day resets per-day mileage", all(v["distance_before_schedule_m"] == 0 for v in tomorrow["vehicles"].values()))
        self.check("next-day retry creates only one successor", self.post(f"/api/dispatch/runs/{did}/next-day", next_command)["dispatch_id"] == tomorrow["dispatch_id"])
        self.post("/api/dispatch/runs/PLAN-DEMO-DAY2/depart", {"command_id": "demo-go-day2", "speed": 0})
        self.snapshots["day1"] = parked
        self.snapshots["day2"] = self.settle("PLAN-DEMO-DAY2", lambda b: b["status"] == "completed" and b["route_view"]["metrics"]["still_returning"] == 0)
        self.snapshots["case"] = closed
        self.snapshots["generated"] = generated

    def simple_plan(self, did, *, delay=False):
        body = {"dispatch_id": did, "command_id": "create-" + did, "algorithm": "greedy",
            "operating_date": DAY, "constraints": {"max_vehicles": 3, "max_stops_per_vehicle": 6,
                "mileage_limit_m": 150000, "terminal_facility_ids": ["W-WESTGATE"] if delay else ["D-NORTHPOINT", "D-HOUGANG"]},
            "orders": [{"order_id": "O-" + dest, "product_id": "vaccine_2_8", "origin_facility_id": "W-WESTGATE",
                "destination_facility_id": "H-" + dest, "quantity": 20, "temperature_zone": "chilled",
                "earliest_min": 540,
                "latest_min": {"KTPH": 800, "CGH": 625, "NTFGH": 640}[dest] if delay else 1020}
                for dest in (["KTPH", "CGH", "NTFGH"] if delay else ["CGH", "NUH"])],
            "inventory": [{"lot_id": "LOT-" + did, "product_id": "vaccine_2_8", "facility_id": "W-WESTGATE",
                "available_quantity": 200, "temperature_zone": "chilled"}],
            "vehicles": [{"vehicle_id": f"V-{i}", "capacity": 100, "temperature_zone": "chilled",
                "start_facility_id": "W-WESTGATE"} for i in [1, 2, 3]]}
        self.post("/api/dispatch/runs", body)
        return self.post(f"/api/dispatch/runs/{did}/depart", {"command_id": "go-" + did, "speed": 0})

    def failure(self):
        did = "PLAN-DEMO-FAILURE"
        departed = self.simple_plan(did)
        vid = next(v for v, b in departed["vehicles"].items() if b["remaining_order_ids"])
        request = {"failed_vehicle_id": vid, "current_time_min": 540}
        preview = self.post(f"/api/dispatch/runs/{did}/failure-preview", request)
        candidate = preview["selected_candidate"]
        self.check("mechanical rescue does not invent handover", candidate["recovery_mode"] == "replacement_delivery" and candidate["transfer_facility_id"] is None)
        command = {**request, "replacement_vehicle_id": candidate["vehicle_id"], "command_id": "demo-failure"}
        accepted = self.post(f"/api/dispatch/runs/{did}/failure-accept", command)
        self.check("mechanical rescue retry is idempotent", self.post(f"/api/dispatch/runs/{did}/failure-accept", command)["version"] == accepted["version"])
        final = self.settle(did, lambda b: b["status"] == "completed" and b["route_view"]["metrics"]["still_returning"] == 0)
        self.check("failed orders remain failed; only replacements deliver",
            all(final["orders"][oid]["status"] == "failed" for oid in preview["failed_order_ids"])
            and all(final["orders"][oid]["status"] == "delivered" for oid in preview["replacement_order_ids"]))
        self.snapshots["failure"] = final

    def delay(self):
        did = "PLAN-DEMO-DELAY"
        self.simple_plan(did, delay=True)
        request = {"current_time_min": 540, "delay_min": 30}
        preview = self.post(f"/api/dispatch/runs/{did}/delay-preview", request)
        candidate = next((c for c in preview["candidates"] if c["replan_available"]), None)
        self.check("delay fixture has a feasible recovery", candidate is not None)
        command = {**request, "vehicle_id": candidate["vehicle_id"], "expected_version": preview["state_version"],
            "remaining_order_ids_after": candidate["remaining_order_ids_after"], "command_id": "demo-delay"}
        self.post(f"/api/dispatch/runs/{did}/delay-accept", {**command, "expected_version": preview["state_version"] - 1}, status=409)
        accepted = self.post(f"/api/dispatch/runs/{did}/delay-accept", command)
        self.check("delay replan improves misses", candidate["replanned"]["predicted_late_order_count"] < candidate["baseline"]["predicted_late_order_count"])
        self.check("delay accept matches displayed stop sequence", accepted["vehicles"][candidate["vehicle_id"]]["remaining_order_ids"] == command["remaining_order_ids_after"])
        self.check("delay retry is idempotent", self.post(f"/api/dispatch/runs/{did}/delay-accept", command)["version"] == accepted["version"])
        self.snapshots["delay_preview"] = preview
        self.snapshots["delay"] = self.settle(did, lambda b: b["status"] == "completed" and b["route_view"]["metrics"]["still_returning"] == 0)

    def insufficient_and_groups(self):
        for scenario in ["multi_source", "capacity_shortage"]:
            generated = self.post("/api/dispatch/simulated-orders", {"scenario": scenario,
                "seed": SEED, "operating_date": DAY, "order_count": 8})
            preview = self.post("/api/dispatch/plan", generated["plan"])
            if scenario == "capacity_shortage":
                self.check("resource shortage is explicitly infeasible", not preview["feasible"] and any(z["unserved"] for z in preview["zones"]))
            else:
                self.check("all source/temperature groups are retained", len(preview["zones"]) >= 3)
            self.snapshots[scenario] = preview


def run_acceptance(workdir: Path, *, graph=False):
    # Refuse reuse: preserving evidence is more useful than silently overwriting.
    workdir.mkdir(parents=True, exist_ok=False)
    DemoTime.instant = datetime.datetime(2026, 10, 1, 9)
    with patch.object(service, "DISPATCH_DATABASE_URL", str(workdir / "dispatch.sqlite3")), \
         patch.object(service, "RUNS_FILE", workdir / "runs.jsonl"), \
         patch.object(service, "_audit", lambda *a, **kw: None), \
         patch.object(tracking, "datetime", SimpleNamespace(datetime=DemoTime)), \
         TestClient(app) as client:
        # False explicitly means unsynced, NOT a fake successful graph write.
        with patch.object(service, "write_case", service.write_case if graph else lambda r: False):
            acceptance = Acceptance(client)
            acceptance.main_day()
            acceptance.failure()
            acceptance.delay()
            acceptance.insufficient_and_groups()
            if graph:
                queue = acceptance.get("/api/graph-sync")
                acceptance.check("live graph has no unconfirmed case mirrors", queue["pending"] == queue["processing"] == 0 and queue["synced"] == 1)
                rid = acceptance.snapshots["case"]["run_id"]
                why = acceptance.post("/api/qa", {"question_type": "why_disposition", "run_id": rid})
                chain = acceptance.post("/api/qa", {"question_type": "audit_chain", "run_id": rid})
                evidence = {(e["node_type"], e["node_id"]) for e in chain["evidence"]}
                acceptance.check("live QA explains the saved disposition", why["status"] == "ok" and chain["status"] == "ok")
                acceptance.check("live audit includes occurrence and replacement destination",
                    {("Facility", "W-WESTGATE"), ("Facility", acceptance.snapshots["case"]["event"]["destination_facility_id"]),
                     ("ReshipmentOrder", f"RO-{rid}")} <= evidence)
                acceptance.snapshots["qa"] = {"why": why, "chain": chain, "queue": queue}
            report = {"status": "passed", "seed": SEED, "operating_date": DAY,
                "graph_mode": "live" if graph else "not_verified", "clock_mode": "controlled_wall_time_real_ticks",
                "check_count": len(acceptance.checks), "checks": acceptance.checks, "snapshots": acceptance.snapshots}
            (workdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="NEW directory; existing directories are refused")
    parser.add_argument("--graph", action="store_true", help="use the configured, seeded Neo4j")
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix="pharma-demo-")) / "acceptance"
    try:
        report = run_acceptance(output, graph=args.graph)
    except Exception as exc:
        print(f"FAIL: {exc}; partial evidence retained at {output}", file=sys.stderr)
        return 1
    print(f"PASS: {report['check_count']} checks; evidence: {output / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
