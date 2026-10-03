"""Portable audit snapshot exports. No reassessment or operational commands."""
import datetime
import hashlib
import html
import json
import re

from optimisation.case_action_guard import case_action_guard
from optimisation.case_repository import read_case_originals
from optimisation.dispatch_repository import load_run
from optimisation.dispatch_state import state_to_dict
from knowledge_graph.coverage import audit_cases


class AuditCaseNotFound(KeyError):
    """Distinguish an unknown ID from a known but malformed source record."""


def snapshot(service, run_id):
    with case_action_guard(service.DISPATCH_DATABASE_URL):
        originals, queue = read_case_originals(service.DISPATCH_DATABASE_URL, legacy_file=service.RUNS_FILE)
        original = next((r for r in originals if r["run_id"] == run_id), None)
        if original is None:
            raise AuditCaseNotFound(run_id)
        current = service.find_run(run_id)
        delivery = {"status": "not_linked", "orders": []}
        did = current.get("handling_dispatch_id") or original["event"].get("dispatch_id")
        if did:
            try:
                state = state_to_dict(load_run(service.DISPATCH_DATABASE_URL, did))
                ids = {oid for oid in [original["event"].get("order_id"), "RO-" + run_id] if oid}
                # Include mechanical successors, not unrelated delivery orders.
                while True:
                    expanded = ids | {oid for oid, o in state["orders"].items() if o.get("replaces_order_id") in ids}
                    if expanded == ids:
                        break
                    ids = expanded
                orders = {oid: o for oid, o in state["orders"].items() if oid in ids}
                delivery = {"status": "recorded_state_not_live_gps", "dispatch_id": did,
                            "dispatch_version": state["version"], "dispatch_status": state["status"], "orders": orders,
                            "replacement_status": current.get("replacement_status")}
            except KeyError:
                delivery = {"status": "linked_dispatch_missing", "dispatch_id": did, "orders": []}
        try:
            graph = audit_cases([original], queue)
            graph = {k: v for k, v in graph.items() if k != "cases"} | {"case": graph["cases"][0]}
        except Exception:
            graph = {"status": "unavailable", "note": "Graph coverage not verified; queue acknowledgement is not proof of graph completeness"}
        payload = {
            "schema": "pharmacoldops-case-audit-v1", "run_id": run_id,
            "original_registration": original,
            "effective_assessment": {k: current.get(k) for k in ["effective_disposition", "effective_reshipment_required",
                "effective_destination_facility_id", "decision_source", "review_status", "execution_locked"]},
            "review_history": current.get("review_history", []),
            "operational_progress": {k: current.get(k) for k in ["processing_status", "workflow_version", "workflow_history", "handling_dispatch_id"]},
            "delivery": delivery, "graph": graph,
            "limitations": ["demonstration_not_clinical_or_compliance_certification", "reviewer_identity_self_declared_not_authenticated",
                            "original_graph_explains_original_assessment_not_human_verdict", "timestamps_preserved_as_recorded_legacy_timezone_may_be_unspecified"],
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        return {"exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "content_sha256": digest, "hash_scope": "payload_without_exported_at_and_hash_fields_not_a_digital_signature", **payload}


def filename(run_id, extension):
    return "case-audit-" + re.sub(r"[^A-Za-z0-9_-]", "_", run_id)[:100] + "." + extension


def render(report, lang="zh"):
    zh = lang == "zh"
    labels = (["案例审计报告", "演示记录，不构成真实药品处置授权或合规认证。人工身份为自报，非认证签名。",
               "原始登记与自动建议（保持不变）", "当前有效处置", "人工审核记录", "处理与结案记录", "关联配送执行快照", "实际图谱覆盖检查", "完整机器可读快照"] if zh else
              ["Case audit report", "Demo record, not authorization for real drug disposition or compliance certification. Reviewer identity is self-declared, not an authenticated signature.",
               "Original registration and recommendation (unchanged)", "Current effective disposition", "Human review history", "Handling and closure history", "Linked delivery snapshot", "Actual graph coverage check", "Complete machine-readable snapshot"])
    def escape(value):
        return html.escape(str(value), quote=True)
    def section(title, value):
        text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        return f"<section><h2>{escape(title)}</h2><pre>{escape(text)}</pre></section>"
    original = report["original_registration"]
    readable = {k: v for k, v in original.items() if k not in {"temperature_context", "temperature_assessment", "ml_contexts", "ml_assessments", "event_context", "event_v2_context"}}
    temperature = original.get("temperature_assessment")
    if temperature:
        readable["temperature_summary"] = {k: v for k, v in temperature.items() if k != "windows"}
        readable["temperature_summary"].update(interval_count=len(original["temperature_context"]["series"]["intervals"]),
            window_count=len(temperature["windows"]), windows_preview=temperature["windows"][:10])
    if original.get("ml_assessments"):
        readable["model_snapshots"] = [{k: v for k, v in m.items() if k not in {"features", "explanations"}} for m in original["ml_assessments"]]
    sections = section(labels[2], readable)
    sections += "".join(section(title, report[key]) for title, key in zip(labels[3:8],
        ["effective_assessment", "review_history", "operational_progress", "delivery", "graph"]))
    effective = report["effective_assessment"]
    disposition_names = {"release": "放行", "retest": "复检", "scrap": "报废", "quarantine": "继续扣留"} if zh else {"release": "Release", "retest": "Retest", "scrap": "Scrap", "quarantine": "Continue hold"}
    display = {
        "有效处置" if zh else "Effective disposition": disposition_names.get(effective["effective_disposition"], "待审核" if zh else "Awaiting review"),
        "需补发" if zh else "Reshipment required": ("是" if zh else "Yes") if effective["effective_reshipment_required"] else ("否" if zh else "No"),
        "依据来源" if zh else "Decision source": effective["decision_source"],
        "审核状态" if zh else "Review status": effective["review_status"],
        "补发目的地" if zh else "Reshipment destination": effective["effective_destination_facility_id"] or "—",
        "执行锁定" if zh else "Execution locked": ("是" if zh else "Yes") if effective["execution_locked"] else ("否" if zh else "No"),
    }
    summary = "".join(f"<tr><th>{escape(key)}</th><td>{escape(value)}</td></tr>" for key, value in display.items())
    observation_note = ("本案例仅登记观察数据，未进行自动规则评估；原始 quarantine 表示操作扣留，不是新增的药品质量判定。" if zh else
                        "Observation-only registration: no automatic rule assessment. Original quarantine denotes an operational hold, not a new drug-quality verdict.") if original.get("automatic_assessment_available") is False else ""
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(labels[0])} · {escape(report['run_id'])}</title>
<style>body{{font-family:system-ui,sans-serif;color:#172033;max-width:1000px;margin:32px auto;padding:0 24px}}h1{{font-size:25px}}h2{{font-size:18px;border-bottom:1px solid #cbd5e1;padding-bottom:8px}}.note{{padding:12px;background:#fffbeb;border:1px solid #fbbf24}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6;background:#f8fafc;padding:12px}}section{{margin:24px 0}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border:1px solid #cbd5e1;padding:8px;text-align:left}}@media print{{body{{margin:0;max-width:none}}h2{{break-after:avoid}}pre{{background:none}}details:not([open]){{display:none}}}}</style></head><body>
<h1>{escape(labels[0])} · {escape(report['run_id'])}</h1><p class="note">{escape(labels[1])}</p>
<p>UTC: {escape(report['exported_at'])}<br>SHA-256: {escape(report['content_sha256'])}</p>
<p>{escape(observation_note)}</p><table>{summary}</table>{sections}<details><summary>{escape(labels[8])}</summary>{section(labels[8], report)}</details></body></html>"""
