/* Knowledge-graph Q&A (concept mockup) — keyword table lives in each locale as
   data (L.qa.answers, L.qa.fallback); first match wins, exactly like the demo's
   askKG(). Pure. */
export function askKG(q, L) {
  const s = q.toLowerCase();
  for (const a of L.qa.answers) {
    for (const kw of a.kw) {
      if (s.includes(kw)) return a.reply;
    }
  }
  return L.qa.fallback;
}

/* Coarse client-side routing to the structured /api/qa contract. This is a
   small deterministic vocabulary, not natural-language classification. */
const TYPE_KEYWORDS = {
  why_disposition: ["为什么", "依据", "why", "隔离原因", "判定原因"],
  audit_chain: ["链路", "追溯", "audit", "全过程", "chain"],
  product_requirements: ["阈值", "储存要求", "threshold", "requirement", "允许时长"],
  disposition_stats: ["统计", "分布", "多少例", "stats", "比例"],
};

export function classifyQuestion(q) {
  const s = q.toLowerCase();
  for (const [type, keywords] of Object.entries(TYPE_KEYWORDS)) {
    if (keywords.some((keyword) => s.includes(keyword.toLowerCase()))) return type;
  }
  return null;
}
