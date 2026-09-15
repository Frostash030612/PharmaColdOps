/* EN locale — every user-facing string the demo shows, extracted verbatim from
   frontend/index.html (both HTML markup and the embedded JS word tables).
   Structural per-locale asymmetries are DATA here (dispo.badge, audit.stageRaw,
   audit.scenTmpl, timeline.badge, packagingVal, durUnit …), never code branches. */

export default {
  singapore: {
  "title": "Singapore delivery network",
  "note": "1 depot / 10 delivery sites · close a case to load its route",
  "assumption": "Demand, capacity and time windows are simulated. Temperature or disposition changes do not recalculate routes.",
  "active": "This disposition recommends reshipment. The fixed example below is available for reference.",
  "activeLive": "This archived reshipment case was solved by the backend; its re-routing plan is shown below.",
  "idle": "No reshipment needed for this disposition. You can still explore the delivery demo.",
  "greedy": "Greedy",
  "ortools": "Optimized",
  "distance": "Distance",
  "vehicles": "Vehicles",
  "served": "Planned stops",
  "violations": "Violations",
  "vehicle": "Vehicle",
  "depot": "Depot",
  "stop": "Stop",
  "arrival": "Arrival",
  "service": "Service starts",
  "demand": "Demand",
  "window": "Time window",
  "select": "Select a map marker or a stop below to inspect its schedule",
  "tiles": "Basemap unavailable. Actual road routes remain visible.",
  "mapLabel": "Singapore road delivery map",
  "reset": "Fit all routes",
  "savings": "Less distance than greedy",
  "units": "units",
  "noStop": "Depot departure / return",
  "km": "km",
  "liveRoute": "Live route for this case",
  "demoRoute": "Fixed demo route",
  "liveOperation": "Live delivery operation (real stock and vehicles)",
  "dispatchStatus": "Dispatch status",
  "ordersDelivered": "Delivered / orders",
  "stockLeft": "Stock left",
  "commitReshipment": "Add this resupply to the operation",
  "closeAndDispatch": "Close case and dispatch resupply",
  "depart": "Depart",
  "simClock": "Sim clock",
  "speedReal": "real",
  "speedFast": "60x",
  "speedFaster": "300x",
  "needsApi": "This disposition needs a resupply; connect the backend (?api=) to dispatch.",
  "noReshipment": "This disposition needs no resupply.",
  "committing": "Checking stock and vehicles\u2026",
  "committed": "\u2713 Resupply added to the operation",
  "fromCase": "from case",
  "loadingRoute": "Calculating this case route…",
  "dailyPlan": "🎲 Generate today's delivery plan",
  "dailyCreating": "Planning…",
  "dailyPreview": "Plan preview",
  "dailyConfirm": "Confirm plan and create the operation",
  "dailySimulated": "Simulated data: hospitals and receiving windows come from the committed road network, but the daily demand and fleet are this project's demo assumptions, not hospital orders."
},
  header: {
    sub: "Cold-chain temperature-excursion disposition & delivery re-routing",
    pillLive: "● Rule engine v1 · live",
    pillWHO: "WHO TRS 961 Annex 9",
    pillEU: "EU GDP 2013/C 343/01",
    pillDemo: "Interactive demo",
  },

  left: {
    presetsTitle: "Scenario presets",
    cfgTitle: "Rule configuration",
    cfgAllowable: "Allowable duration",
    cfgMkt: "MKT threshold (°C)",
    cfgRetestable: "Retestable",
    cfgReset: "Reset to product defaults",
  },

  center: {
    sandboxTitle: "Decision sandbox",
    sectionTimeline: "Temperature replay",
    play: "▶ Replay",
    pause: "⏸ Pause",
    sectionInputs: "Excursion inputs",
    product: "Product",
    stage: "Stage",
    destination: "Resupply destination",
    packaging: "Packaging",
    randomize: "🎲 Randomize excursion",
    temp: "Excursion temp (°C)",
    dur: "Duration (min)",
    mkt: "Mean Kinetic Temperature — MKT (°C)",
    sectionZone: "Decision boundary map (duration × MKT)",
    sectionRulePath: "Auditable rule path",
    sectionRules: "Rule evaluation (priority order)",
    sectionRisk: "Risk index",
    riskNote: "(rule-derived · deterministic, not an ML model)",
    sectionEvidence: "Why this decision",
  },

  right: {
    rerouteTitle: "Delivery re-routing",
    qaTitle: "Compliance Q&A",
    qaNote: "(structured query · offline fallback)",
    qaPlaceholder: "e.g. what is MKT? when to scrap?",
    qaAsk: "Ask",
    qaLoading: "Querying…",
    qaInitial: "Ask a regulatory question to see a grounded answer.",
    qaNeedsCase: "Close and archive a case first to ask this question.",
    qaOfflineNote: "(offline concept answer, not a live query)",
    qaSource_live: "Live knowledge-graph query",
    qaSource_fallback: "Knowledge graph unavailable; showing offline guidance",
    qaSource_concept: "Offline keyword answer",
    qaSource_notice: "Archived case required",
    qaStatus_no_case: "No record of this case in the knowledge graph.",
    qaStatus_insufficient_evidence: "(The graph holds no regulation/SOP for this rule, so the answer follows the no-evidence-no-answer rule.)",
    qaStatus_unsupported: "This question is outside the supported intents (why-disposition, audit chain, product requirements, disposition statistics).",
    qaSource_insufficient: "Case exists, evidence missing",
    qaSource_unsupported: "Unsupported question",
    /* Evidence node-type labels — mirrors docs/KG_SCHEMA_v1.md §1. */
    qaNode: {
      Product: "Product", Regulation: "Regulation", SOP: "SOP", ExcursionEvent: "ExcursionEvent",
      Disposition: "Disposition", Cause: "Cause", Facility: "Facility", Shipment: "Shipment",
      ReshipmentOrder: "ReshipmentOrder",
    },
  },

  audit: {
    title: "Audit trail",
    colTime: "Time",
    colScenario: "Scenario",
    colProduct: "Product",
    colDispo: "Disposition",
    colPath: "Rule path",
    /* scenario cell: EN shows the raw stage code (stageRaw:true); ZH looks it up */
    stageRaw: true,
    scenTmpl: "{stage} · {temp}°C / {dur}min",
  },

  /* cross-session case history (GET /api/runs, backend run log) */
  history: {
    title: "Case history",
    sub: "Archived by the Python backend (data/audit/runs.jsonl) — one record per closed inbound case, newest first.",
    colCase: "Case",
    colWhen: "Recorded",
    colProduct: "Product",
    colExcursion: "Excursion",
    colDispo: "Disposition",
    colRisk: "Risk",
    colWhy: "Why",
    scenTmpl: "{stage} · {temp} °C / {dur} min · MKT {mkt} °C",
    reshipTag: "↻ reship",
    count: "{n} archived",
    refresh: "↻ Reload",
    expand: "Open in full view",
    loadHint: "Load this case into the sandbox",
    loading: "Loading past cases…",
    error: "Could not load case history from the backend.",
    waiting: "Waiting for the backend connection…",
    empty: "No archived cases yet — start one with “New inbound” and close it, and it appears here.",
    offline: "Case history is stored with the Python backend and shown in API mode. Reopen this page with ?api=<backend> (or reconnect) to see past records.",
  },

  /* centered modal: add a new inbound case (opened from the header + button) */
  newInbound: {
    openTip: "New inbound — fill in the shipment case, then close & archive",
    title: "New inbound",
    sub: "Record this new shipment's excursion. The disposition previews live; nothing is saved until you close the case.",
    batch: "Batch / remark (optional)",
    batchPh: "e.g. batch 2026-0901",
    rules: "Rule config (optional)",
    resetSpec: "Product defaults",
    preview: "Live preview",
    archive: "✓ Close & archive",
    cancel: "Cancel",
    error: "Could not archive this case — please retry.",
  },

  modal: {
    close: "Close",
  },

  footer:
    "PharmaColdOps · interactive demo — API mode loads live re-routing results for archived cases and structured knowledge-graph queries; offline mode uses precomputed routes and keyword answers; order parameters are simulated.",

  /* --- structural sentence templates (interpolated by pure libs / components) --- */
  templates: {
    pathLine: "{product} ({min}–{max} °C) at {temp} °C for {dur} min (MKT {mkt} °C, allowable {allow} min) → {disp}: {reason}",
    scenarioMeta: "{temp} °C · {dur} min · MKT {mkt} °C · {stage}",
  },

  /* packaging <select> option labels */
  packagingOptions: { intact: "Intact", compromised: "Compromised" },

  /* --- product display names (keys = product_id) --- */
  products: {
    vaccine_2_8: "Vaccine (2–8 °C)",
    frozen_m20: "Frozen biologic (−25…−15 °C)",
    insulin_2_8: "Insulin (2–8 °C)",
    mrna_ultracold: "mRNA vaccine (−90…−60 °C)",
  },

  /* --- stage display names (keys = stage id) --- */
  stages: {
    transit: "In transit",
    warehouse: "Warehouse",
    airport_dwell: "Airport dwell",
    last_mile: "Last mile",
  },

  /* --- dispositions: label + badge box text (EN badge = first letter) --- */
  dispo: {
    release: { label: "Release", badge: "R" },
    retest: { label: "Retest", badge: "R" },
    quarantine: { label: "Quarantine", badge: "Q" },
    scrap: { label: "Scrap", badge: "S" },
  },

  /* --- six rules in priority order (index + 1 = rule_no) --- */
  rules: [
    "Freeze damage: freeze-sensitive product at or below 0 °C → scrap",
    "Compromised packaging during an excursion → scrap",
    "Duration ≥ 2× allowable, or MKT ≥ threshold + 3 °C → scrap",
    "Duration > allowable, or MKT > threshold → scrap",
    "Retestable and near the edge (duration ≥ 0.8× allowable, or MKT ≥ threshold − 0.5 °C) → retest",
    "Otherwise → release",
  ],

  ruleText: {
    1: { reason: "freeze damage; freeze-sensitive product exposed below freezing point", regulation: "WHO TRS 961 Annex 9 §6.9 — freeze-sensitive products must be protected against temperatures below 0 °C; discarding a frozen batch is the project rule for irreversible freeze damage" },
    2: { reason: "packaging compromised during excursion", regulation: "EU GDP 2013/C 343/01 — packaging integrity must be preserved during transport" },
    3: { reason: "excursion severity beyond any acceptable margin", regulation: "WHO TRS 961 Annex 9 — excursion beyond acceptable stability margin" },
    4: { reason: "exceeded allowable excursion; any overrun is unacceptable (no hold band)", regulation: "WHO TRS 961 Annex 9 / EU GDP 2013/C 343/01 — excursion beyond the labelled range requires assessment; project policy (both annotators, 2026-09-11) treats any overrun as unacceptable" },
    5: { reason: "within limits but near threshold; confirm by testing", regulation: "EU GDP 2013/C 343/01 — confirm within-threshold excursions by testing" },
    6: { reason: "excursion within acceptable safety range", regulation: "WHO TRS 961 Annex 9 — within acceptable range" },
  },

  /* --- risk root-cause wording (keys = cause_code) --- */
  causeText: {
    frozen: "Freeze damage (≤ 0 °C)",
    packaging: "Packaging breach",
    overtemp: "Reefer setpoint / over-temperature",
    duration: "Excursion duration exceeds allowable",
    mkt: "MKT above threshold",
    near: "Near threshold — retest to confirm",
    inband: "In band, no anomaly",
    minor: "Minor temperature deviation",
  },

  /* --- evidence chip words per row/level --- */
  evLbl: {
    packaging: { ok: "OK", breach: "BREACHED" },
    temp: { ok: "OK", breach: "OUT OF RANGE" },
    freeze: { ok: "OK", severe: "FROZEN" },
    duration: { ok: "OK", near: "NEAR (≥0.8×)", breach: "BREACHED (>A)", severe: "SEVERE (≥2×)" },
    mkt: { ok: "OK", near: "NEAR (≥T−0.5)", breach: "BREACHED (>T)", severe: "SEVERE (≥T+3)" },
  },

  /* --- evidence rows (labels, value words, limit templates) --- */
  evidence: {
    labels: { packaging: "Packaging", temp: "Excursion temp", freeze: "Freeze risk", duration: "Duration", mkt: "MKT" },
    /* packaging value: EN keeps the raw code (as the source did) */
    packagingVal: { intact: "intact", compromised: "compromised" },
    durUnit: "min",
    limitTemp: "limit {v} °C",
    limitFreeze: "freezing point 0 °C",
    limitDur: "allowable {v} min",
    limitMkt: "threshold {v} °C",
    summary: "→ Rule {no}: {reason}",
    reg: "⚖ {reg}",
  },

  /* --- decision banner --- */
  banner: {
    reshipHead: "Reshipment",
    reshipReq: "REQUIRED",
    reshipNo: "Not required",
  },

  risk: {
    causeLabel: "Top root cause: {cause}",
  },

  /* --- timeline SVG words + per-locale badge geometry (offsets from width W) --- */
  timeline: {
    axis: "Time (min)",
    maxLabel: "max {v}°",
    minLabel: "min {v}°",
    excursion: "⚠ EXCURSION",
    badge: { xOffset: 152, w: 140, textOffset: 82 },
    readout: "t = {now} / {total} min",
  },

  zone: {
    xAxis: "Duration (min)",
    yAxis: "MKT (°C)",
    noteOverride: "Rule 1 override active: compromised packaging during excursion → scrap (map shows rules 2–5).",
    noteNormal: "Map shows rules 2–5 (packaging intact). Drag the duration / MKT sliders to move the dot across decision boundaries.",
  },

  route: {
    noRoute: "no route",
    idle: "Shipment cleared — no re-routing required.",
    depot: "DEPOT",
    modeOptimized: "Optimized",
    modeOriginal: "Original (baseline)",
    metricDist: "Distance",
    metricTime: "Route time",
    metricCost: "Cost",
    metricViol: "Violations",
    allocStrong: "Replacement stock allocated:",
    allocPost: "240 doses of {name} from Central Depot, dispatched with a cold-chain reefer.",
    detail: "Time window {tw} · {zone} · demand {demand} doses · stop #{pos} of {total}",
  },

  apiPill: {
    good: "● API · Python engine",
    bad: "● API down · local fallback",
    connecting: "● API connecting…",
  },

  qa: {
    answers: [
      { kw: ["mkt", "mean kinetic"], reply: "Mean Kinetic Temperature (MKT) compresses a temperature–time profile into a single stability-relevant value, so a short hot spike can be compared against the product's stability threshold." },
      { kw: ["scrap", "discard", "destroy"], reply: "Per EU GDP 2013/C 343/01 and WHO TRS 961 Annex 9, product exceeding its stability margin must be scrapped with a documented destruction record and deviation report." },
      { kw: ["quarantine", "hold"], reply: "Quarantine segregates the batch in labelled storage pending Quality review; release requires a documented risk assessment against the excursion data." },
      { kw: ["retest", "test"], reply: "Retesting confirms potency and stability when an excursion is within the retestable margin; the result feeds the final disposition." },
      { kw: ["release"], reply: "Release requires the excursion to be within the acceptable safety range — MKT and duration below their thresholds — with a traceable rule path on record." },
      { kw: ["reroute", "route", "deliver", "reship"], reply: "The optimiser re-routes replacement stock via VRPTW with time windows, multi-temperature zones, capacity limits and stockout priority." },
      { kw: ["gdp", "ich", "who"], reply: "Regulatory basis: WHO TRS 961 Annex 9 (model guidance for storage and transport), EU GDP 2013/C 343/01, and ICH stability guidelines." },
    ],
    fallback: "The knowledge graph links product, route, event, rule and SOP entities, so every answer is grounded in the governing regulation rather than generated from thin air.",
  },
};
