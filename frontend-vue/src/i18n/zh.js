/* ZH locale — every user-facing string from frontend/index-zh.html, verbatim.
   Structurally the same tree as en.js; differences are DATA (Chinese label/badge,
   translated stage/evidence values, minutes unit, narrower timeline badge …). */

export default {
  header: {
    sub: "冷链药品温度超限处置与配送重新规划",
    pillLive: "● 规则引擎 v1 · 实时",
    pillWHO: "WHO TRS 961 附录 9",
    pillEU: "EU GDP 2013/C 343/01",
    pillDemo: "交互演示",
  },

  left: {
    presetsTitle: "场景预设",
    cfgTitle: "规则配置",
    cfgAllowable: "允许超限时长",
    cfgMkt: "MKT 阈值（°C）",
    cfgRetestable: "可复验",
    cfgReset: "重置为产品默认值",
  },

  center: {
    sandboxTitle: "决策沙盒",
    sectionTimeline: "温度回放",
    play: "▶ 回放",
    pause: "⏸ 暂停",
    sectionInputs: "超限输入",
    product: "产品",
    stage: "阶段",
    packaging: "包装",
    randomize: "🎲 随机超限事件",
    temp: "超限温度（°C）",
    dur: "时长（分钟）",
    mkt: "平均动力学温度 — MKT（°C）",
    sectionZone: "决策边界图（时长 × MKT）",
    sectionRulePath: "可审计规则路径",
    sectionRules: "规则评估（优先级顺序）",
    sectionRisk: "风险指数",
    riskNote: "（规则启发式 · 确定性，非 ML 模型）",
    sectionEvidence: "为什么这么判",
  },

  right: {
    rerouteTitle: "配送重新规划",
    qaTitle: "合规问答",
    qaNote: "（知识图谱 · 概念）",
    qaPlaceholder: "例如：什么是 MKT？什么时候报废？",
    qaAsk: "提问",
    qaInitial: "提出合规问题，查看基于法规的回答。",
  },

  audit: {
    title: "审计追踪",
    colTime: "时间",
    colScenario: "场景",
    colProduct: "产品",
    colDispo: "处置",
    colPath: "规则路径",
    stageRaw: false,
    scenTmpl: "{stage} · {temp}°C / {dur}分钟",
  },

  footer:
    "PharmaColdOps · 交互演示 —— 规则引擎与风险指数为实时逻辑（风险指数由同一组阈值导出，确定性）；VRPTW 配送规划与知识图谱问答为概念示意。",

  /* --- structural sentence templates (interpolated by pure libs / components) --- */
  templates: {
    pathLine: "{product}（{min}–{max} °C）在 {temp} °C 持续 {dur} 分钟（MKT {mkt} °C，允许 {allow} 分钟）→ {disp}：{reason}",
    scenarioMeta: "{temp} °C · {dur} 分钟 · MKT {mkt} °C · {stage}",
  },

  /* packaging <select> option labels */
  packagingOptions: { intact: "完好", compromised: "破损" },

  products: {
    vaccine_2_8: "疫苗（2–8 °C）",
    frozen_m20: "冷冻生物制品（−25…−15 °C）",
    insulin_2_8: "胰岛素（2–8 °C）",
    mrna_ultracold: "mRNA 疫苗（−90…−60 °C）",
  },

  stages: {
    transit: "运输中",
    warehouse: "仓库",
    airport_dwell: "机场滞留",
    last_mile: "最后一公里",
  },

  /* ZH badge box shows the full label (2 characters). */
  dispo: {
    release: { label: "放行", badge: "放行" },
    retest: { label: "复验", badge: "复验" },
    quarantine: { label: "隔离", badge: "隔离" },
    scrap: { label: "报废", badge: "报废" },
  },

  rules: [
    "冻结损坏：冻敏产品在 0 °C 及以下 → 报废",
    "超限期间包装破损 → 报废",
    "时长 ≥ 2× 允许值，或 MKT ≥ 阈值 + 3 °C → 报废",
    "时长 > 允许值，或 MKT > 阈值 → 隔离",
    "可复验且接近边界（时长 ≥ 0.8× 允许值，或 MKT ≥ 阈值 − 0.5 °C）→ 复验",
    "否则 → 放行",
  ],

  ruleText: {
    1: { reason: "冻结损坏；冻敏产品暴露在冰点以下", regulation: "WHO TRS 961 附录 9 — 冻敏疫苗冻结即失效" },
    2: { reason: "超限期间包装破损", regulation: "EU GDP 2013/C 343/01 — 运输过程中包装完整性必须保持" },
    3: { reason: "超限严重程度超出任何可接受范围", regulation: "WHO TRS 961 附录 9 — 超限超出可接受稳定性余量" },
    4: { reason: "超出允许超限；隔离待质量评估", regulation: "WHO TRS 961 附录 9 / EU GDP — 超限时隔离待质量评估" },
    5: { reason: "未超限但接近阈值；复验确认", regulation: "EU GDP 2013/C 343/01 — 阈内超限以复验确认" },
    6: { reason: "超限在可接受安全范围内", regulation: "WHO TRS 961 附录 9 — 在可接受范围内" },
  },

  causeText: {
    frozen: "冻结损坏（≤0 °C）",
    packaging: "包装破损",
    overtemp: "制冷设定点/超温越限",
    duration: "超限时长超允许值",
    mkt: "MKT 超过阈值",
    near: "接近阈值，需复验确认",
    inband: "在带内，未见异常",
    minor: "轻微温度偏离",
  },

  evLbl: {
    packaging: { ok: "正常", breach: "破损" },
    temp: { ok: "正常", breach: "超范围" },
    freeze: { ok: "正常", severe: "已冻结" },
    duration: { ok: "正常", near: "接近（≥0.8×）", breach: "超出（>A）", severe: "严重（≥2×）" },
    mkt: { ok: "正常", near: "接近（≥T−0.5）", breach: "超出（>T）", severe: "严重（≥T+3）" },
  },

  evidence: {
    labels: { packaging: "包装", temp: "超限温度", freeze: "冻结风险", duration: "时长", mkt: "MKT" },
    /* ZH packaging value is the translated word, not the code */
    packagingVal: { intact: "完好", compromised: "破损" },
    durUnit: "分钟",
    limitTemp: "上限 {v} °C",
    limitFreeze: "冰点 0 °C",
    limitDur: "允许 {v} 分钟",
    limitMkt: "阈值 {v} °C",
    summary: "→ 规则 {no}：{reason}",
    reg: "⚖ {reg}",
  },

  banner: {
    reshipHead: "补发",
    reshipReq: "需要",
    reshipNo: "不需要",
  },

  risk: {
    causeLabel: "首要根因：{cause}",
  },

  timeline: {
    axis: "时间（分钟）",
    maxLabel: "上限 {v}°",
    minLabel: "下限 {v}°",
    excursion: "⚠ 超限",
    badge: { xOffset: 118, w: 106, textOffset: 65 },
    readout: "t = {now} / {total} 分钟",
  },

  zone: {
    xAxis: "时长（分钟）",
    yAxis: "MKT（°C）",
    noteOverride: "规则 1 覆盖生效：超限期间包装破损 → 报废（图中仅显示规则 2–5）。",
    noteNormal: "图中显示规则 2–5（假设包装完好）。拖动时长 / MKT 滑杆，让圆点跨越决策边界。",
  },

  route: {
    noRoute: "无需路由",
    idle: "货物放行 —— 无需重新配送。",
    depot: "仓库",
    modeOptimized: "优化方案",
    modeOriginal: "原始方案（基线）",
    metricDist: "距离",
    metricTime: "路径时长",
    metricCost: "成本",
    metricViol: "违规数",
    allocStrong: "已分配补发库存：",
    allocPost: "{name} 共 240 剂，自中央仓库发出，冷藏车配送。",
    detail: "时间窗 {tw} · {zone} · 需求 {demand} 剂 · 第 {pos} / {total} 站",
  },

  apiPill: {
    good: "● API · Python 引擎",
    bad: "● API 不可达 · 本地兑底",
    connecting: "● API 连接中…",
  },

  qa: {
    answers: [
      { kw: ["mkt", "平均动力学"], reply: "平均动力学温度（MKT）把一段温度-时间曲线压缩成单个与稳定性相关的值，使一次短暂升温可对照产品的稳定性阈值来评估。" },
      { kw: ["报废", "销毁", "丢弃"], reply: "依据 EU GDP 2013/C 343/01 与 WHO TRS 961 附录 9，超出稳定性边界的药品必须报废，并附销毁记录与偏差报告。" },
      { kw: ["隔离", "扣留", "hold"], reply: "隔离将批次置于隔离且贴标存储，等待质量审评；放行需基于超限数据完成书面风险评估。" },
      { kw: ["复验", "检测", "测试"], reply: "当超限处于可复验边界内时，复验确认效价与稳定性；结果作为最终处置的依据。" },
      { kw: ["放行", "释放"], reply: "放行要求超限处于可接受安全范围内——MKT 与时长均低于阈值——且留痕记录规则路径。" },
      { kw: ["配送", "路由", "补发", "路线"], reply: "优化器通过 VRPTW 重新规划补发库存，考虑时间窗、多温区、容量约束与断货优先级。" },
      { kw: ["gdp", "ich", "who"], reply: "法规依据：WHO TRS 961 附录 9（存储与运输示范指南）、EU GDP 2013/C 343/01，以及 ICH 稳定性指南。" },
    ],
    fallback: "知识图谱将产品、路线、事件、规则与 SOP 等实体关联，使每个回答都基于适用的法规，而非凭空生成。",
  },
};
