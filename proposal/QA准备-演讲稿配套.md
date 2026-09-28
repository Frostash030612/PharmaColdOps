# PharmaColdOps 问答准备册（Proposal Presentation · 2026-09-29）

> 用法：**英文粗体那段是可直接照念的答句**；下面的中文是"为什么这么答"与出处。
> 铁律三条：① 先给结论，再给边界（"we did / we did not"）；② 任何数字都要能说出处；③ 不知道就说不知道，并说清"要补什么才能知道"——**编一个答案比承认不知道扣分多得多**。
>
> **打印版**：[`QA准备-演讲稿配套.docx`](QA准备-演讲稿配套.docx)（A4、1.5cm 页边距、每问不跨页；由 `scripts/build_qa_docx.py` 生成，改完本文件重跑该脚本即可）。

---

## 0. 上台前 60 秒自检（数字口径）

| 项目 | 口径 |
|---|---|
| 部署面 | **23 API 路径 / 24 个操作**，其中 dispatch **15 个路径 / 16 个操作**（deck 第 7 页的 "15" 就是路径数） |
| 代码/测试 | **305 个测试函数 / 34 个含测试的文件**（第 35 个 `.py` 是 `conftest.py`）；后端约 7,700 行、前端约 5,500 行；24 个 `.vue`（23 个组件 + `App.vue`） |
| 处置评测 | **54/57 = 94.7% agreement**（rubric v1.1）；提交件口径 **39/57**（rubric v1）；κ = **0.6434**（目标 0.80）；报废召回 33/33、**隔离 0/3** |
| 路线 | **142.6305 → 133.8073 km，−6.19%**，0 违规 / 0 未服务；Solomon c101/c201 在 10s 达到**已发表最优** |
| 风险模型 | LightGBM，70/15/15 划分：**F1 0.691 / ROC-AUC 0.925**；原因分类 **Top-1 0.143 < 多数类 0.161**（负面结果） |
| 数据规模 | 25 条归档案例、56 条调度作业（`data/audit/dispatch.sqlite3`）；新加坡 **19 节点**（1 主仓 + 1 第三方仓 + 14 医院 + 3 分拨点）、**342 条有向路径**；图谱实拍 **9 节点 / 8 类关系** |
| 求解器 | OR-Tools **RoutingModel + `PARALLEL_CHEAPEST_INSERTION` 首解 + Guided Local Search**，**不是 CP-SAT** |
| 处置语义 | 四类：release / quarantine / retest / scrap；**补发是独立物流动作，不是第五类** |
| 边界 | 不替代质量负责人审批，不授权真实放行/销毁/运输；不声称运营节约 |

---

## 1. 最容易被打的 12 问（按概率排序）

### Q1. "Isn't 94.7% marking your own homework?"
**Wholly fair. It is agreement with our own rubric, not field accuracy, and we say so on the slide. We evaluate in three separate layers: unit tests prove the implementation matches our frozen rules; the human gold standard — 57 scenarios, independently annotated by two of us and arbitrated by a third — shows where the written rules differ from human judgement; and domain validity would need product stability evidence or external review, which we have not done and therefore do not claim. Our annotators only agreed with each other at κ = 0.6434, so we report that too rather than re-tuning the rubric to look better.**

- 为什么这么答：把"自我评估"这个指控直接转成你们自己的三层评估框架（提案 §8.3），并主动把 κ 不够亮出来——评委的打分点是"你们知不知道自己的证据有多强"。
- 出处：提案 §8.3；`data/processed/agreement_stats.md`；冻结测试 `tests/test_rule_engine.py`。
- **别答**："这是 independent evaluation"（人工 gold 是你们四个人标的，不 independent）。

### Q2. "Your submitted proposal says 39/57, the slide says 54/57. Which is true?"
**Both, and the difference is documented. After submission, rubric v1.1 fixed rule 4's quarantine-versus-scrap ambiguity as `scrap`; the rubric, the engine and the frozen tests were updated in the same change. That cleared 15 of the differences and left 3 — S034/S035/S052, where gold says quarantine and the engine says release, release, retest. We report both numbers and both rubric versions. The cold-excursion evidence gap behind that rule is still open.**

- 为什么这么答：这是"提交后改口径"的质疑。唯一安全的答法是**同时给出两个数字与两个版本**，并说明改动是同批做的（不是事后调参凑分）。
- 出处：提案 §8.3；README「提交件与源稿的差异」。
- **别答**："the submitted number was wrong"（等于承认提交件有错）。
- **别做**：不要现场说"我们现在是 94.7% 准确率"——见 Q1。

### Q3. "Why not use an LLM for the disposition advice?"
**Because the online recommendation has to be inspectable, citable and auditable. A quality decision needs a rule path someone can re-check, so the deterministic rule engine is the sole semantic source of the online recommendation, and ML scores never enter the decision API. Our `/api/qa` endpoint is a constrained question-type router over parameterised Cypher — not free-text generation. An LLM is not required for the MVP; we would consider it for phrasing, not for deciding.**

- 出处：提案 §6.2、§6.5。
- 加分句（可选）："We would rather ship a narrow thing that is defensible than a broad thing that is not."

### Q4. "You didn't do user research or talk to a quality lead. How do you know this is the real problem?"
**Correct — we have no interviews and no operational data, and we state that as a limitation. What we do have is the published requirement: WHO TRS 961 Annex 9, EU GDP, ICH and CDC all put the deviation assessment and the record of that assessment on the responsible person. Our claim is narrower than market fit: we show that the reasoning path can be produced, connected to re-planning and made reproducible. Market value still needs user interviews and operational data.**

- 出处：提案 §3.3、§4、§11。
- **别答**："我们问过同学"之类没有记录的东西。

### Q5. "κ = 0.6434 is below your own 0.80 target. Doesn't that invalidate the gold standard?"
**It limits it, and that is why we report support counts next to every class. The disagreement is concentrated in the quarantine/scrap boundary, which is exactly the ambiguity we then wrote into rubric v1.1. We deliberately did not re-rate the rubric to push κ up: we report 0.6434 and keep the 3 gold quarantine cases rather than tuning them away.**

- 加分句："With 3 quarantine cases, no metric on that class is statistically meaningful — we report it as a support-count limitation, not as performance."
- 出处：提案 §8.3；`data/processed/agreement_stats.md`。

### Q6. "Quarantine recall is 0/3 — is your system dangerous?"
**Two things. First, that class has only 3 gold cases and they are the 3 residual differences we flag as gold-side to review, so we do not read 0/3 as a stable estimate. Second, the high-consequence direction we do measure well is scrap recall, 33 out of 33 — 100%. And the boundary the system is least reliable on is quarantine versus scrap, which is precisely why the prototype does not authorise release, destruction or transport: a quality lead signs it off.**

- 为什么这么答：先把统计问题说清（n=3 不能推断），再给出**真正的高后果指标**（报废 33/33），最后回到"不改人工审批"这条边界——这是最能让评委放心的组合。
- **别答**："0/3 是因为 gold 标错了"（直接把责任推给标注，听起来像甩锅；说"gold-side to review"是已登记的待复核项，措辞要中性）。

### Q7. "You claim a −6.19% routing improvement. Is that an operational saving?"
**No, and we do not claim one. That is a single simulated Singapore instance on real OpenStreetMap roads: demand, fleet and time windows are simulated, and travel times are free-flow estimates. Our external anchor is the Solomon benchmarks, where the same solver reaches the published best known solution on c101 and c201 within ten seconds. Operational savings would need real orders and real travel times.**

- 出处：提案 §6.4、§8.2；`data/processed/routing_comparison.md`。
- **别答**："相当于节省 6.19% 成本"（会被追问基线是谁的运营数据）。

### Q8. "Your datasets are synthetic. What can you actually conclude?"
**Each dataset is used only for its own task and its nature is disclosed on the slide: the silent-failure set is about 8,000 shipment summaries whose authenticity is unconfirmed and which looks synthetic, the vaccine-distribution set is around 26,700 rows and also appears synthetic, and the facility-monthly set is a simulation. So the risk and cause results describe those datasets only — we do not extrapolate them to real shipments. Routing uses the published Solomon benchmark, and the Singapore case uses a real OSM network with clearly simulated business assumptions.**

- 加分句："Every figure on the results slide is reproducible from the repo, and the data dictionary records the licence and the nature of each source."

### Q9. "Where do your thresholds come from? Are 2–8 °C and 30 minutes validated?"
**The sources are ICH stability guidance for the acceptable-window logic, and WHO TRS 961 Annex 9, EU GDP and CDC as procedural or transport guidance. The specific numbers in our configuration are engineering assumptions, not product-level limits, and the config records them as such with their sources. Validating them would need stability data for a named product, which is outside a prototype.**

- 出处：`src/rule_engine/rules_config.json` 的 `_note` 与 `_sources`；提案 §3.1、§7.2；`docs/阈值证据表_v1.md`。
- **别答**："这些阈值就是法规规定的"（评审若是法规背景会直接追问条款）。

### Q10. "You built a knowledge graph and a chat interface. What's actually reasoning here?"
**The online reasoning is a priority-ordered rule engine: first match wins, and every output carries the rule id, the regulation or SOP it cites and the evidence status. The graph is a structured case store, not a reasoning engine — `/api/qa` routes limited question types to parameterised Cypher and returns four machine-readable states: ok, no case, insufficient evidence, unsupported. We call that cognitive rather than generative, and we do not describe it as natural-language understanding.**

- 出处：提案 §6.1、§6.5。
- 加分句："If a judge asks 'which of the four IRS technique groups is this?', it is the cognitive-systems group — knowledge base plus a constrained interface — and we cover all four groups overall."

### Q11. "Is OR-Tools CP-SAT under the hood?"
**No. It is the OR-Tools routing library: `RoutingModel` with Guided Local Search, and for the published results we set `PARALLEL_CHEAPEST_INSERTION` as the first-solution strategy. That last part was a real bug hunt — the default `PATH_CHEAPEST_ARC` constructs no feasible start on r101/rc101, so the solver returned empty solutions at every time budget. The fix was a different construction strategy, not a longer time limit.**

- 这是**技术挑战**类问题的标准答案（guideline 8 要"技术挑战及如何解决"），主动讲比被问出来强。
- 出处：`src/optimisation/ortools_solver.py`；`data/processed/routing_comparison.md` §口径。

### Q12. "What's the contribution if every component is off the shelf?"
**The contribution is the unbroken, inspectable chain inside one prototype: temperature event → disposition with a cited rule → reshipment order → route under capacity and time windows → queryable evidence, all reproducible from the repo. We do not claim a new algorithm, and we do not claim to be first at monitoring — commercial platforms already do temperature monitoring and parts of quality automation.**

- 加分句："We also hold ourselves to reporting the parts that do not work: a below-baseline cause classifier and a κ below target are both on the slide."

---

## 2. 分主题备查

### A. 市场与定位

**A1. "How do you differ from Controlant / Sensitech / Tive?"**
**We don't claim to be first. Those platforms monitor temperature and automate parts of the quality process — Controlant's Product Stability Automation, for example, determines release status from a product's stability profile. Our increment is narrower and inspectable: the disposition, the reshipment order, the route and the cited evidence stay in one case chain you can re-run. Where we cannot verify a vendor's capability we record it as unknown rather than assuming it away.**

**A2. "Who would pay for this?"**
**On the evidence we have, we can only name the roles the workflow serves — the quality lead who signs a deviation off, the dispatcher who re-plans, and the auditor who rebuilds the decision (proposal §4). Pricing and willingness to pay need the user interviews we have not done.**

**A3. "Is this commercially viable in Singapore?"**
**We can't answer that from what we built. The Singapore case is a controlled simulation over a real road network; it demonstrates the pipeline, not the market.**

### B. 范围与技术组

**B1. "Which IRS technique groups do you cover?"**
**All four, against a requirement of three: decision automation (priority-ordered rules and four dispositions), business resource optimisation (capacity- and time-window VRPTW with a greedy baseline), knowledge discovery and data mining (shipment-level failure classification, facility-level candidate-cause classification, SHAP attribution), and cognitive systems (Neo4j knowledge base with a constrained query interface). The ML work is offline and never enters the decision API.**

**B2. "You listed multi-temperature zones and carbon emissions in the proposal. Are those built?"**
**No — they are listed as optional extensions, gated on acceptance of the main chain. Same for alternative-stock selection. What is built is the single-depot reshipment path.**

**B3. "What did you explicitly exclude?"**
**Production ERP or WMS integration, real IoT deployment, clinical validation or formal compliance certification, patient data, automatic authorisation of real product disposition, and actual transport execution.** *(Carbon-emission and multi-temperature objectives are not exclusions — they are listed as optional extensions, gated on main-chain acceptance.)*

**B4. "Don't you need to run GA since you listed evolutionary computing?"**
**We implemented a genetic algorithm and it does not beat the routing solver on these instances, so we do not present it as a delivered algorithm. Our fourth group is satisfied by the knowledge base and its interface, not by the GA.**

### C. 数据与知识

**C1. "How did you get the data and verify licences?"**
**All datasets are public and downloaded with the licence verified at source; the data dictionary records the source, licence and nature of each one, and an audit script re-checks it. Electric Sheep Africa and OSM attributions are retained in the repo.**

**C2. "What is the knowledge graph built from?"**
**Structure comes from the regulatory and SOP material we cite — WHO TRS 961 Annex 9, EU GDP, ICH and CDC — plus our product-class configs, the facilities in the Singapore scenario, and the datasets' records. The live capture in our proposal shows one closed case: 9 nodes and 8 relationship types.**

**C3. "Are you doing recommendation or diagnosis?"**
**Neither in a clinical sense. The online part is decision automation with evidence citation; the diagnosis-like work is an offline experiment, and we report its Top-1 as below the majority baseline rather than dressing it up.**

**C4. "Is your QA service hallucinating?"**
**There is no generation step: `/api/qa` routes a limited set of question types to parameterised Cypher and returns one of four states — ok, no case, insufficient evidence, unsupported. If the graph is unavailable it returns 503 and the client falls back to a keyword template, which is visible to the user rather than hidden.**

### D. 评测与实验

**D1. "Why is your risk model only F1 0.691?"**
**It is a single stratified random split on a suspected-synthetic dataset, and F1 is threshold-dependent — we select the threshold on the validation split. Multi-fold experiments and a stricter split are the next step, and we say in the proposal that these numbers describe that dataset only.**

**D2. "Why not more folds?"**
**Time, and we would rather report one honest split now than average away the variance. Multi-fold risk experiments are a committed next step.**

**D3. "Why report a classifier that loses to the majority baseline?"**
**Because hiding it would be worse. The negative result is informative: with ten cause classes and this feature set, candidate ranking is not solved, so cause analysis stays offline and out of the decision path.**

**D4. "What is your evaluation plan for the final deliverable?"**
**Acceptance runs over the failure states, not just the happy path: reshipment required and not required, infeasible route, no evidence, service failure and duplicate case closure, plus a clean-environment reproduction of the whole loop.**

### E. 实现与工程

**E1. "Can I see it running?"**
**Yes. Online mode only: start the backend, open the client with `?api=`, pick an archived closed case to open the decision sandbox, ask an evidence question, generate today's batch and confirm it (confirming also departs), preview adding the case to a running vehicle, then submit it into the live operation — which reserves stock and assigns a vehicle — and watch the simulated clock advance on the map.**

- 两个坑（自己人必须知道，别在台上试）：
  - **离线模式点不开决策沙盒**（历史为空），必须带 `?api=` 且后端已起。
  - **前端没有调用 `/api/route` 的入口**——"点一下就算出该案例路线"的按钮不存在；路线是在线走 `/api/dispatch/*` 那条链出来的。

**E2. "What's still missing?"**
**Cloud deployment, de-duplication of repeated case closures, a larger candidate destination pool, passing the excursion location into the case form, and the integrated acceptance run plus a clean-environment reproduction — all listed on the slide.**

**E3. "What state is it persisted in, and is it audit-grade?"**
**Case history is JSONL and dispatch runs are in SQLite with optimistic version checks; the graph write is best-effort. We explicitly do not claim audit-grade durability.**

**E4. "Why a rule engine instead of an ML classifier for disposition?"**
**Because disagreement has to be attributable. A rule engine can show which rule fired and which evidence it cited; a classifier's error would not be reconstructable for an audit. The trade-off is brittleness at boundaries — which is what the 3 residual differences are.**

### F. 团队与合规

**F1. "What did each member do?"**
**A — rules, regulatory evidence and evaluation; B — data, risk and candidate-cause experiments, SHAP; C — routing, reshipment and the dispatch operation; D — knowledge graph, QA service, API and frontend. Each module has more than one author in the repository because we cross-review.**

**F2. "How much AI was used?"**
**Our AI-use note is section 15 of the proposal, and it lists what was assisted and what was not. Generative AI helped with drafting, translation, layout and cross-checking, and with scenario drafts during development. It was not used as a source of stability or compliance conclusions. The human gold standard came from our own independent annotation and arbitration, and we remain responsible for every citation, rule assumption, experiment and submission. The presentation you are hearing is spoken by us, not generated.**

- 出处：提案 §15「补充说明 AI 的使用」（EN: §15 Supplementary Note on AI Use）。
- **别答**："We didn't use AI"（提案里写了用了；不一致会被扣诚信分）。也**别**把工具名说成声明里没有的东西——按声明里的说法讲。
- 加分句（可选）："The check scripts in the repo that compare the slides against re-measured repo facts are part of that verification habit."

**F3. "How many man-days?"**
**Around ten man-days per member, the module's estimate. Note that our scope was scoped to that budget — that is why extensions are gated and the loop is single-depot.**

**F4. "Can it be deployed in a real hospital?"**
**Not as it stands, and we would not want it to be. It is an evaluable prototype: no production hardening, no validated thresholds, no integration with quality systems, and the final disposition is signed off by a human.**

---

## 3. 兜底话术（真的答不上来时用）

| 情形 | 照念 |
|---|---|
| 数字记不清 | **"I don't want to quote a number I can't place — it's in the repo, and I'd rather pull it up than guess."** |
| 没做过的事 | **"We have not done that, so we can't claim it. What it would take is ___."** |
| 对方假设错了 | **"That's a fair question, but it rests on an assumption we didn't make — we claim X, not Y."** |
| 问到竞品细节 | **"We couldn't verify that vendor's capability, so we recorded it as unknown rather than asserting it."** |
| 问到很远的未来方向 | **"That's listed as an optional extension, gated on the main chain passing acceptance."** |
| 完全不会 | **"I don't know. Can I take that as a question to come back on?"**（然后记下来，散场后回复——评委会记住这个动作） |

---

## 4. 四人分工（谁接哪类问题）

| 谁 | 接什么 |
|---|---|
| A · Xu Wenzhe | 处置规则与阈值来源、法规依据、gold 与 κ、39/57 vs 54/57、评估方法、项目定位与范围 |
| B · Zhu Jianyu | 数据集性质与许可、风险模型指标、原因分类负面结果、SHAP、多折实验计划 |
| C · Wang Lepeng | 求解器与首解策略、路由结果、补发/调度链路、GA 与扩展项、新加坡算例规模 |
| D · Shen Ziyi | 图谱与 `/api/qa` 四态、API 面与持久化、前端演示与离线模式、部署缺口、演示操作 |

跨领域时**先接话再转**："That's mainly C's area — Lepeng, on the solver configuration?"
