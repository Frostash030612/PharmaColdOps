/* Audit trail rows — one <tr> of HTML per logged decision, mirroring the demo's
   addAudit() byte-for-byte. The scenario cell is a per-locale asymmetry carried
   as DATA: EN prints the raw stage code (L.audit.stageRaw:true) while ZH looks
   the stage up in L.stages. Pure — the caller prepends and caps at 8. */
import { fmt, interp } from "./format.js";
import { DISPO_COLOR } from "../data/products.js";

export function auditRowHtml(current, decision, L) {
  const dispo = decision.disposition;
  const color = DISPO_COLOR[dispo];
  const specName = L.products[current.product_id] || current.product_id;

  const stageWord = L.audit.stageRaw
    ? current.stage
    : (L.stages[current.stage] || current.stage);
  const scenario = interp(L.audit.scenTmpl, {
    stage: stageWord,
    temp: fmt(current.excursion_temp_c),
    dur: current.duration_min,
  });

  return `<tr>
    <td>${new Date().toLocaleTimeString()}</td>
    <td>${scenario}</td>
    <td>${specName}</td>
    <td><span class="tag" style="background:${color}1a;color:${color}">${L.dispo[dispo].label}</span></td>
    <td style="color:#64748b">${decision.rulePath}</td>`;
}

export function scenarioCellText(current, L) {
  const stageWord = L.audit.stageRaw
    ? current.stage
    : (L.stages[current.stage] || current.stage);
  return interp(L.audit.scenTmpl, {
    stage: stageWord,
    temp: fmt(current.excursion_temp_c),
    dur: current.duration_min,
  });
}
