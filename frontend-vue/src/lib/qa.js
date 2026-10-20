/* Deterministic bounded routing. Concepts are not case-specific graph evidence. */
export const QA_QUERY_TYPES = ["why_disposition", "audit_chain", "product_requirements", "cause_context", "disposition_stats"];
export const CASE_QUESTION_TYPES = ["why_disposition", "audit_chain", "cause_context"];

function normalise(value) {
  return typeof value === "string" ? value.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim() : "";
}

export function isOutsideQaScope(question) {
  const s = normalise(question);
  return /\b(weather|forecast|rain|rainfall)\b|天气|下雨|气象预报/.test(s)
    || /真实效价|临床效价|证明.*(?:药品安全|临床有效)|实际(?:效力|效价)|用药剂量|患者诊断/.test(s)
    || /\b(?:certify|prove|confirm|guarantee)\b.*\b(?:potency|clinical efficacy|clinical safety)\b/.test(s)
    || /\b(?:actual|real) potency\b|\b(?:patient diagnosis|dosage recommendation)\b/.test(s);
}

function matchesKeyword(question, keyword) {
  const s = normalise(question), word = normalise(keyword);
  if (!word) return false;
  if (word === "who") return s === "who" || /\bWHO\b/.test(question) || /world health organi[sz]ation/i.test(question);
  return /^[a-z0-9 ]+$/.test(word) ? new RegExp(`\\b${word}\\b`, "i").test(s) : s.includes(word);
}

export function conceptAnswer(question, L) {
  if (isOutsideQaScope(question)) return null;
  const answers = L.qa.answers.filter(a => a.kw.some(keyword => matchesKeyword(question, keyword)));
  return answers.length === 1 ? answers[0].reply : null;
}

export function askKG(question, L) {
  if (isOutsideQaScope(question)) return L.right.qaStatus_unsupported;
  return conceptAnswer(question, L) || L.qa.fallback;
}

export function classifyQuestion(question) {
  const s = normalise(question);
  if (!s || isOutsideQaScope(question)) return null;
  const audit = /审计|追溯|链路|全过程|处理历程|处理历史|\b(?:audit|trace|traceability|timeline|provenance|chain)\b/.test(s);
  const product = /储存要求|存储要求|产品要求|温度阈值|允许时长|储存温度|\b(?:storage requirements?|product requirements?|temperature thresholds?|storage limits?|allowed excursion|allowable duration)\b/.test(s);
  const stats = /处置(?:数量|分布|统计|比例)|(?:统计|分布|比例).*处置|多少例|\b(?:disposition stats|disposition statistics|disposition distribution|disposition counts?)\b/.test(s)
    || /\b(?:stats|statistics|distribution|counts?|proportions?|percentages?)\b.*\b(?:cases?|dispositions?)\b/.test(s)
    || /\b(?:cases?|dispositions?)\b.*\b(?:stats|statistics|distribution|counts?|proportions?|percentages?)\b/.test(s);
  const cause = /(?:根因|原因).*(?:阶段|产品|最常见|多见|背景|分布)|最常见.*(?:根因|原因)/.test(s)
    || /\b(?:cause|root cause)\b.*\b(?:stages?|products?|common|contexts?|patterns?|frequent)\b/.test(s)
    || /\b(?:where|stages?|products?)\b.*\b(?:cause|root cause)\b/.test(s);
  const why = !cause && !product && (/(?:为何|为什么|依据|判定原因|处置原因).*(?:判定|处置|报废|隔离|复检|放行|案例)|(?:案例|判定|处置).*(?:依据|原因)/.test(s)
    || /\b(?:why|reason|basis|justify|justification|evidence)\b.*\b(?:case|disposition|decision|scrapped?|quarantined?|retest(?:ed)?|release[ds]?)\b/.test(s));
  const types = [["audit_chain", audit], ["product_requirements", product], ["disposition_stats", stats],
    ["cause_context", cause], ["why_disposition", why]].filter(([, matched]) => matched).map(([type]) => type);
  return types.length === 1 ? types[0] : null;
}

export function safeEvidenceLink(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

export function questionScopeMismatch(question, type, {runId, productId}) {
  const s = normalise(question);
  const cases = [...new Set(s.match(/\br\d{8}-\d{6}-\d{6}-[a-f0-9]{8}\b/g) || [])];
  const products = ['vaccine_2_8','frozen_m20','insulin_2_8','mrna_ultracold'].filter(id => s.includes(id));
  if (/\binsulin\b|胰岛素/.test(s) && !products.includes('insulin_2_8')) products.push('insulin_2_8');
  if (/\bmrna\b|超低温/.test(s) && !products.includes('mrna_ultracold')) products.push('mrna_ultracold');
  if (type === 'disposition_stats' && (cases.length || products.length)) return true; // no implicit aggregate filtering
  return cases.some(id => id !== normalise(runId)) || products.some(id => id !== productId);
}

export function decodeQaResponse(value, L) {
  const states = ["ok", "no_case", "insufficient_evidence", "unsupported"];
  if (!value || !states.includes(value.status) || typeof value.answer !== "string" || !Array.isArray(value.evidence)) {
    throw new Error("Invalid structured QA response");
  }
  if (value.evidence.some(item => !item || ["node_type", "node_id", "summary"].some(key => typeof item[key] !== "string"))) {
    throw new Error("Invalid QA evidence");
  }
  if (value.status === "ok") return { answer: value.answer, evidence: value.evidence, source: "live" };
  if (value.status === "insufficient_evidence") return {
    answer: `${value.answer} ${L.right.qaStatus_insufficient_evidence}`, evidence: value.evidence, source: "insufficient",
  };
  return { answer: L.right[`qaStatus_${value.status}`], evidence: [], source: value.status === "unsupported" ? "unsupported" : "notice" };
}
