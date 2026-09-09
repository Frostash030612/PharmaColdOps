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
