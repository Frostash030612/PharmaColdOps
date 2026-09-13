# 来源核实报告（第二轮）：ICH Q1A(R2)、HSA GDP、未核实的 EU GDP 章节号、两个 SOP 节点

核实对象：`src/knowledge_graph/build_graph.py` 中 `REGULATIONS`（第 73–146 行）与 `SOPS`（第 152–174 行）声明的法规节点。
本轮重点：**A. ICH Q1A(R2)**（本次核心）、**B. HSA GDP Guidance Notes**、**C. 三个尚未核实过的 EU GDP 章节号**、**D. 两个 SOP 节点的来源**。

---

## 0. 方法与限制（先声明，避免误读）

- `web_fetch` 不接受 `application/pdf`；本会话沙箱内 shell 直连网络不可用（沿用上一轮记录的 `schannel: SEC_E_NO_CREDENTIALS`）。**PDF 原文一律经 `r.jina.ai` 文本抽取代理获取**，抽取文本即本轮证据来源；下文所有引号内容均出自该抽取文本。
- **交叉校验（本轮同样做了，未省略）**：
  - ICH Q1A(R2)：抽取结果报告 `Number of Pages: 24`；文档自带的目录（TABLE OF CONTENTS）页码序列终于 "4. REFERENCES … 17"，正文末页为 "Stability Testing of New Drug Substances and Products 18" —— 18 页正文 + 前置/附录页，与 24 页抽取结果自洽。
  - ICH Q1E：抽取报告 `Number of Pages: 19`，正文末页标注 "Evaluation of Stability Data 15" + Figures 页，自洽。
  - HSA GDP：抽取报告 `Number of Pages: 21`；文档每页页眉自带 "Page N of 21"（可见 Page 2–20），**逐页自洽**。
  - EU GDP：HTML 抽取的段号 `1.1./1.2./3.2.1./3.3./9.2./9.3./9.4.` 与 "C 343/1, 23.11.2013" 页眉同源，且与上一轮 §9.2/§9.3 的抽取结果**逐字一致**（同一 CELEX 文档，两次独立抽取可复现）。
  - PMC 论文：抽取报告 `Number of Pages: 8`；文章页眉为 "Bull World Health Organ 2010;88:624–631"（624–631 = 8 页），并可见页脚页码 625/626/627/628/629/630/631，**与 8 页抽取结果自洽**。
- 判定分级（与上一轮报告口径一致）：`VERIFIED` = 见到原始文件且条款内容与主张相符；`PARTIAL` = 文件真实但条款号/粒度对不上，或只能核到文档级、或仅二手来源；`UNVERIFIED` = 找不到或打不开原始文件，或原文中无此内容；`CONTRADICTED` = 见到原始文件且与主张矛盾。
- **本轮无一项**结论是通过"搜索摘要"顶替原文得到的（见 §5 失败清单：凡未亲见者一律标 UNVERIFIED）。
- **与上一轮结论的口径一致性**：WHO TRS 961 Annex 9 §6.2、§6.9、EU GDP §9.2、USP MKT 定义在〈1079.2〉不在〈1079〉 —— 本轮未重做，报告中引用时保持同一口径。

---

## 1. 逐条判定表

| # | 主张位置 | 主张 | 判定 | 证据 / 原文片段 | 实际可用粒度 |
|---|---|---|---|---|---|
| **A1** | `build_graph.py:143` `source_url` = `https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf` | 该 PDF 可取得、真实存在 | **VERIFIED** | HTTP 200 经代理取得全文，**24 页**。标题页：`INTERNATIONAL CONFERENCE ON HARMONISATION OF TECHNICAL REQUIREMENTS FOR REGISTRATION OF PHARMACEUTICALS FOR HUMAN USE / ICH HARMONISED TRIPARTITE GUIDELINE / STABILITY TESTING OF NEW DRUG SUBSTANCES AND PRODUCTS / Q1A(R2) / Current Step 4 version / dated 6 February 2003`。Document History 表末行：`Q1A(R2) … Approval by the Steering Committee of the second revision directly under Step 4 without further public consultation … 6 February 2003`。发布机构 = ICH（本文件自称 Harmonised Tripartite Guideline，由 ICH Expert Working Group 制定）。**版本日期 = 2003-02-06** | **文档级（一手官方 PDF）** |
| **A2** | `:141` `clause` = `"Stability testing of new drug substances and products"` | 这是**文档标题**，不是条款标题 | **PARTIAL（粒度被夸大）** | 该字符串是 PDF 每一页页眉/封面的大写文档标题（`STABILITY TESTING OF NEW DRUG SUBSTANCES AND PRODUCTS`）。Q1A(R2) 的实际结构**没有**任何名为该标题的编号条款；实际编号为 `1. INTRODUCTION`（1.1/1.2/1.3）、`2. GUIDELINES`（2.1 Drug Substance：2.1.1–2.1.10；2.2 Drug Product：2.2.1–2.2.10）、`3. GLOSSARY`、`4. REFERENCES`，**并且确实存在 2.1/2.2/2.3 这类三级编号**（如 2.1.7.1、2.2.7.4）。把文档标题写进名为 `clause` 的字段，会让下游误读为"已核到条款级" | **只有文档级**：`clause` 字段必须改写为文档级标识（见 §2.1） |
| **A3a** | `:142` summary 归属 1 = `storage range` | Q1A(R2) 是"储存范围"的依据 | **VERIFIED** | 原文片段（§2.1.7.2 `Drug substances intended for storage in a refrigerator`）：`Long term  5°C ± 3°C  12 months`；`Accelerated  25°C ± 2°C/60% RH ± 5% RH  6 months`。§2.1.7.3 `Drug substances intended for storage in a freezer`：`Long term  - 20°C ± 5°C  12 months`。§2.1.7.4：`Drug substances intended for storage below -20°C should be treated on a case-by-case basis.` 药品侧同构：§2.2.7.4 冷藏 `5°C ± 3°C`，§2.2.7.5 冷冻 `- 20°C ± 5°C`，§2.2.7.6 同"case-by-case"。另 §1.3：`to establish a re-test period for the drug substance or a shelf life for the drug product and recommended storage conditions`；§2.1.10/§2.2.10 要求标签储存声明须基于稳定性评价 | **条款级**（§2.1.7.2 / §2.1.7.3 / §2.2.7.4 / §2.2.7.5） |
| **A3b** | `:142` summary 归属 2 = `allowable excursion duration` | Q1A(R2) 是"允许偏移时长"的依据 | **CONTRADICTED（归属不成立）** | 通读全文（24 页）后确认：**Q1A(R2) 全文没有"允许偏移时长"这一概念，也没有给出任何偏移时长数值**。全文对偏移的唯一处理是"须被评估"：§2.1.7 `Data from the accelerated storage condition and, if appropriate, from the intermediate storage condition can be used to evaluate the effect of short term excursions outside the label storage conditions (such as might occur during shipping).`；§2.2.7.4 `a discussion should be provided to address the effect of short term excursions outside the label storage condition`。文中出现的唯一数值上限是**稳定性研究箱内偏移**（非运输偏移）：Glossary `Storage condition tolerances`：`Excursions that exceed the defined tolerances for more than 24 hours should be described in the study report and their effect assessed.` —— 它规定的是"超过 24 小时要写进研究报告并评估"，**不是**"允许 24 小时偏移" | **归属删除**：Q1A(R2) 只能支撑"偏移须由稳定性数据评估"，**不能**支撑任何 `allowable_duration` 数值 |
| **A3c** | `:142` summary 归属 3 = `MKT ceiling` | Q1A(R2) 是"MKT 上限"的依据 | **CONTRADICTED（归属不成立，但存在同名术语）** | Q1A(R2) **确实定义**了 mean kinetic temperature，但**没有**"上限"概念。原文片段（Glossary）：`Mean kinetic temperature — A single derived temperature that, if maintained over a defined period of time, affords the same thermal challenge to a drug substance or drug product as would be experienced over a range of both higher and lower temperatures for an equivalent defined period. The mean kinetic temperature is higher than the arithmetic mean temperature and takes into account the Arrhenius equation. When establishing the mean kinetic temperature for a defined period, the formula of J. D. Haynes (J. Pharm. Sci., 60:927-929, 1971) can be used.` 该术语的引入语境是**气候分区**（§1.3：`The mean kinetic temperature in any part of the world can be derived from climatic data, and the world can be divided into four climatic zones, I-IV.`），与冷链运输偏移评估无关；全文无任何 MKT 阈值、上限或合格判定 | **术语定义可比上一轮的 USP 归属更早**（Q1A(R2) Glossary 确有 MKT 定义，2003 年），但 **"ceiling" 部分无任何 ICH 依据** |
| **A4** | `:138-144` 整个 ICH 节点 | 是否需要替换出处 | **PARTIAL（需拆分归属）** | 见 §1.2 与 §2.1。要点：Q1A(R2) 对 `storage range` 与 `product-specific stability data` 是恰当的**文档级/条款级**出处；对 `allowable excursion duration` 与 `MKT ceiling` 不成立。ICH 体系内更近的**候选**：**ICH Q1E《Evaluation of Stability Data》**（本轮**已一手核实**：`https://database.ich.org/sites/default/files/Q1E%20Guideline.pdf`，19 页，`Current Step 4 version / dated 6 February 2003`）。Q1E §2.5.1.2（冷藏产品）原文：`If significant change occurs within the first 3 months' testing at the accelerated storage condition … a discussion should be provided to address the effect of short-term excursions outside the label storage condition (e.g., during shipping or handling).`；Appendix A 决策树亦含 `No extrapolation; shorter retest period or shelf life and data covering excursions can be called for`。**但必须同时说明**：Q1E 给出的数字（`up to X + 3 months`、`up to 1.5X, but not exceeding X + 6 months`）是**货架期外推幅度上限**，**不是**允许运输偏移时长上限 | **候选已核实**：Q1E 可进报告，但只能支撑"偏移须被讨论/评估"，**仍然不支撑任何 allowable excursion duration 数值**。ICH 体系内**不存在**给定期限的运输偏移上限指南 |
| **A5** | `:143` 域名 `database.ich.org` + ICH 官方质量页定位 | 域名/路径仍可解析；Q1A(R2) 在官方稳定性格局中的定位 | **VERIFIED** | `https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf` **仍可解析**（HTTP 200，经代理）。官方页 `https://www.ich.org/page/quality-guidelines` 载明：`Q1A(R2) Stability Testing of New Drug Substances and Products … has reached Step 4 of the ICH process in February 2003 … provides recommendations on stability testing protocols including temperature, humidity and trial duration for Climatic Zone I and II … Date of Step 4: 6 February 2003；Status: Step 5`。**HSA, Singapore — Implemented; Date: 1 January 2008; Reference: ASEAN Common Technical Dossier (ACTD) for the registration of pharmaceuticals for human use, Part II: Quality**（这条与项目的新加坡场景直接相关，可直接引用）。另注：`Q1 EWG Stability Testing of Drug Substances and Drug Products` 修订中（`Date of Step 2b: 11 April 2025`，`Status: Step 3`，目标是把 Q1A–Q1F 合并为单一 ICH Q1）——引用时应注明 Q1A(R2) 现处于被合并修订的过程中 | **文档级（官方页一手）** |
| **B1** | `:134` `source_url`（HSA 落地页） | URL 可解析；页面上确实提到该 GDP Guidance Notes | **VERIFIED** | 落地页 HTTP 200，标题 `Good Manufacturing Practice and Good Distribution Practice Standards`（HSA）。原文：`Compliance to our Guidance Notes on Good Distribution Practice [PDF, 263 KB] is mandatory for all local importers and wholesalers of Therapeutic Products, Chinese Proprietary Medicines, Cell, Tissue and Gene Therapy Products and Active Ingredients intended for the Singapore market.` 链接目标为 `https://isomer-user-content.by.gov.sg/409/c19890a5-6658-492d-b8ff-1ec6e9dc9f9c/guide-mqa-013.pdf`（本轮**已取得该 PDF 全文，21 页**） | **落地页 = 指路页（一手，可用于证明"该指南存在且强制"）；但它本身不是指南原文** |
| **B2** | `:130` 标题里的 `rev. 15 Dec 2023` | 版本日期属实 | **VERIFIED（但出处是落地页，不是 PDF）** | 落地页原文（Note 段）：`Note: Our Guidance Notes on Good Distribution Practice is revised on 15 December 2023, primarily to clarify the GDP requirements for the handling of Active Ingredients, under the new Health Products (Active Ingredients) Regulations 2023.` —— **日期确实属实**。**但须注明证据层级**：我取到的指南 PDF 首页只写 `DECEMBER 2023`，文档编号 `GUIDE-MQA-013-012`，**PDF 正文里我没有看到 "15 December 2023" 这个具体日期，也没有看到修订历史表**。因此准确的写法是"HSA 落地页声明本次修订于 2023-12-15"，而不是"PDF 上标注 2023-12-15" | **句子级（HSA 官方页一手声明）** |
| **B3** | `:133` summary `mandatory GDP standard for importers and wholesalers` | 对进口商/批发商强制 | **VERIFIED** | 落地页：`is mandatory for all local importers and wholesalers of Therapeutic Products, … intended for the Singapore market.` 另 `Our GDP auditors will conduct audits on companies in accordance with these GDP standards prior to the issuance of local dealer's licences.` 指南 PDF 词汇表亦以 `Licensee = A licensed importer, wholesaler and/or GDP-certified companies.` 定义适用主体。**注意范围**：强制范围除 Therapeutic Products 外还含 CPM、CTGTP 及 Active Ingredients，项目 summary 只写了 therapeutic products，属**窄于原文**（不算错，但引用时应补全或明确限定） | **句子级，可进报告** |
| **B4** | `:133` summary `aligning storage, transport and temperature-control requirements` | 是否确实涵盖 storage/transport/temperature control | **VERIFIED** | 指南 PDF（21 页）原文：`This guide is intended for those involved in the storage, transportation and distribution of Active Ingredients, Therapeutic Products, …`；§2.7 `Storage conditions for products should be in compliance with the instructions on the product label … The storage areas should be equipped with recorders or devices that will continuously monitor the storage conditions and record the relevant readings such as maximum and minimum temperature and humidity of the day.`；§2.8 `The recorders and devices for monitoring the storage conditions should be located in areas that are most likely to show fluctuations and/or the hottest and coldest locations where appropriate.`；§3.10(d) 运输须 `secure and not subject to unacceptable degrees of heat, cold, light, moisture or other adverse influence`；`For cold chain products, both the requirements as stipulated in this guide and Annex 1 will be applicable.`；**Annex 1 `COLD CHAIN PRODUCTS`**（16 条）含 `written procedures established to ensure that incoming cold chain products are delivered under the storage conditions in compliance with the instructions on the product label, which are based on the results of stability testing`、`The cold room … should be subject to temperature mapping studies`、`temperature excursions` 报警与处理程序、`The temperature conditions of the cold room or refrigerator should be monitored and recorded on a continuous basis`；词汇表 `Cold Chain Products = Products requiring storage condition of not more than 8°C.` | **条款级（§2.7、§2.8、§3.10、Annex 1）——但条款号指向的是 PDF，代码里却没给 PDF 的 URL** |
| **B5** | `:132` `clause` = `"GDP standard for therapeutic products"` | 这是不是条款 | **PARTIAL（粒度被夸大）** | 该字符串**不是**指南中的任何条款标题，也不是文档标题；它是工程自造的**文档级描述**。指南实际结构是 `1 PERSONNEL` … `13 HANDLING OF ACTIVE INGREDIENTS` + `14 GLOSSARY` + `15 REFERENCES` + `Annex 1 COLD CHAIN PRODUCTS` + `Annex 2`；文档自身标题为 `GUIDANCE NOTES ON GOOD DISTRIBUTION PRACTICE`（封面并标 `DECEMBER 2023`，编号 `GUIDE-MQA-013-012`）。另：`:135` 的 `verified` 字段写 `document title/source confirmed`，与 `clause` 字段的"条款级"观感自相矛盾 | **只有文档级**；`clause` 应改写为文档标题+编号（见 §2.2） |
| **C1** | `:96-97` | EU GDP **Chapter 1.2 — Quality system（deviations & CAPA）**：`Deviations from established procedures must be documented and investigated; corrective and preventive actions (CAPA) are taken in line with quality risk management.` | **VERIFIED** | 抽取全文含 `CHAPTER 1 —QUALITY MANAGEMENT`、`1.1.Principle`、`1.2.Quality system`。1.2 正文列举质量体系须确保的事项，原文：`(v)deviations from established procedures are documented and investigated; (vi)appropriate corrective and preventive actions (commonly known as 'CAPA') are taken to correct deviations and prevent them in line with the principles of quality risk management.` **章节号真实存在，内容相符** | **条款级** |
| **C2** | `:105-106` | EU GDP **Chapter 3.2.1 — Temperature and environment control**：含 `temperature mapping before use, monitors placed at the points of greatest fluctuation, re-mapping after significant changes` | **VERIFIED（章节号正确；措辞为轻度改写）** | 抽取全文含 `CHAPTER 3 —PREMISES AND EQUIPMENT`、`3.1.Principle`、`3.2.Premises`、`3.2.1.Temperature and environment control`、`3.3.Equipment`。3.2.1 原文：`An initial temperature mapping exercise should be carried out on the storage area before use, under representative conditions. Temperature monitoring equipment should be located according to the results of the mapping exercise, ensuring that monitoring devices are positioned in the areas that experience the extremes of fluctuations. The mapping exercise should be repeated according to the results of a risk assessment exercise or whenever significant modifications are made to the facility or the temperature controlling equipment.` ⚠️ **特别检查结论：章节号对得上——该内容确实在 3.2.1，不在 3.2 也不在 3.3。**（3.2 `Premises` 讲的是分区、安防、清洁、虫害；3.3 `Equipment` 讲的是校准、报警系统、维护记录。）唯一偏差：代码把 `the areas that experience the extremes of fluctuations` 简写为 `the points of greatest fluctuation`，**属意译而非 verbatim**，`verified` 字段却写 `verbatim match`，该标注不准确 | **条款级**（须把 `verbatim` 改为 `paraphrase`/`near-verbatim`） |
| **C3** | `:123-124` | EU GDP **Chapter 9.4 — Products requiring special conditions**：`Temperature-sensitive products must be transported using qualified equipment (thermal packaging, temperature-controlled containers or vehicles)` | **VERIFIED（章节号正确；措辞为轻度改写）** | 抽取全文含 `CHAPTER 9 —TRANSPORTATION`、`9.1.Principle`、`9.2.Transportation`、`9.3.Containers, packaging and labelling`、`9.4.Products requiring special conditions`。9.4 原文：`For temperature-sensitive products, qualified equipment (e.g. thermal packaging, temperature-controlled containers or temperature-controlled vehicles) should be used to ensure correct transport conditions are maintained between the manufacturer, wholesale distributor and customer.` ⚠️ 另注：9.4 **并非只讲温度敏感品**，其前两段讲麻醉/精神药品与高度活性/放射性物质；且 9.4 还含 `Temperature mapping under representative conditions should be carried out and should take into account seasonal variations.`（若报告需要"再制图"，9.4 也有依据，不必只引 3.2.1）。同样：`must be transported` 是改写（原文为 `should be used`），与 `verbatim match` 标注不符 | **条款级**（须把 `verbatim` 改为 `paraphrase`） |
| **D1a** | `:157` `source_url`（CDC） | 可否取得；是否确为 CDC Temperature Excursion Checklist（May 2014） | **VERIFIED** | HTTP 200 经代理取得，**1 页**。抽取标题：`Vaccine Storage and Handling Toolkit Temperature Excursion Checklist`；正文标题：`CDC's Temperature Excursion Checklist`；页脚日期：`May 2014`。即：**确为 CDC《Vaccine Storage and Handling Toolkit》中的 Temperature Excursion Checklist，2014 年 5 月版** | **文档级（一手官方 PDF）** |
| **D1b** | `:156` summary 的步骤 | 内容是否确含这些步骤 | **VERIFIED** | 逐项对得上（原文）：`Check circuit breakers`、`Door closed`、`Door seal adequate`、`Assess location of temperature monitoring devices for temperature reading`、`Record all temperatures`；`Label exposed vaccines "Do NOT Use" and store under appropriate conditions (set apart from other vaccines)`；`Check temperature of alternate storage unit`、`Vaccines moved to alternate storage unit (move refrigerated vaccines first)`；`Document temperature excursion action taken and results`；`Immunization Program contacted`、`Manufacturer contacted`；`Return vaccines determined to be usable only when storage unit is stable and resume use`；`Vaccines purchased with private funds should be disposed of in consultation with the manufacturer(s) and according to state regulations for medical waste`。另：`1 Checklist for general power loss — Contact utility company / Determine if time to restoration is acceptable / Activate alternate generator if available` 亦在原文 | **文档级到步骤级**（原文为**美国免疫规划语境**，措辞含 `Immunization Program`、`state regulations for medical waste`、`Vaccines for Children (VFC) Program`；移植到新加坡场景时应声明为"程序模板参照"而非本地法规要求） |
| **D2a** | `:164` `source_url`（PMC2908964） | 可否取得；是否为疫苗冻结 shake test 验证研究 | **PARTIAL → 见说明** | **原始 URL `https://pmc.ncbi.nlm.nih.gov/articles/PMC2908964/` 未能取得**：经代理返回 `Checking your browser - reCAPTCHA` / `Warning: This page maybe requiring CAPTCHA`（**反爬拦截，非 404**）。改由 **Europe PMC 镜像**取得全文：`https://europepmc.org/articles/PMC2908964?pdf=render`（HTTP 200，退出为 8 页 PDF 文本）。文题：`Validation of the shake test for detecting freeze damage to adsorbed vaccines`；作者 `Ümit Kartoglu, Nejat Kenan Özgüler, Lara J Wolfson & Wiesław Kurzatkowski`；出处 `Bull World Health Organ 2010;88:624–631 | doi:10.2471/BLT.08.056879`；WHO 作者单位 `Department of Immunization, Vaccines and Biologicals, World Health Organization, Geneva`。**即：文章身份与主题 VERIFIED；但代码所引的 PMC 域名本身在本会话不可直接访问** | **文档级（一手期刊全文，经 Europe PMC 镜像；同一 PMCID）** |
| **D2b** | `:163` 数字 `validated on 475 vials across 8 freeze-sensitive vaccine types` | 475 支 / 8 种是否属实 | **VERIFIED** | 原文（Results）：`The study was conducted with 480 vials of 8 types of freeze-sensitive WHO prequalified vaccines from 10 manufacturers. During the unpacking of vaccines in Warsaw, 5 vials were broken and were excluded from the study. This reduced the sample to 475 vials.`；`A total of 319 vials were not frozen and 156 were frozen.`；Table 3：`Fail 156 / Pass 319 / Total 475`。摘要同义：`A total of 475 vials of 8 different types of World Health Organization prequalified freeze-sensitive vaccines from 10 different manufacturers were used.` **475 与 8 均属实**（8 种 = DTP、DT、dT、TT、HepB、DTP–HepB、DTP–HepB–Hib、Hib liquid；10 家厂商；取样框架总数列合计 480） | **句子级/数字级，可进报告** |
| **D2c** | `:163` 操作描述 `shake … for 10–15 seconds and compare sedimentation side by side` | 与原文是否相符 | **UNVERIFIED（数字部分）；PARTIAL（操作部分）** | **"10–15 seconds" 在本文全文中找不到**——我通读了该 8 页抽取全文，**没有任何秒数出现在 shake 操作描述中**。原文该处是**定性**的：`The two vials are held together in one hand and shaken; they are then placed side by side on a flat surface. Provided the test vial has not been frozen, sedimentation is slower in the test vial than in the control vial that has been frozen and thawed. If the test vial has been frozen, the test and control vials will have similar sedimentation rates.` 判定为"pass/fail"的判据原文为：`If a test vial contents sedimented at a similar or a faster rate than the contents of the frozen control vial, this was recorded as a "fail"; if the vial contents sedimented at a slower rate than the contents of the frozen control vial, this was recorded as a "pass".` 相反，论文报告的是**做出判断所需的时间**：`The shortest decision time was 44 seconds with a 10-dose tetanus toxoid vaccine, and the longest was 20 minutes with a monodose Haemophilus influenzae type b vaccine.`、`all other products were analysed within 1 to 5 minutes.` 论文把 shake 操作的标准写在**外部**材料里：`the standard "Shake test learning guide" (Appendix A, available at: http://www.who.int/vaccines-documents/DocsPDF06/847.pdf, pages 59–62)` —— 该外部 guide 本轮**未能取得**（见 §5）。"compare sedimentation side by side" 与 "同一批次、同厂" 部分：原文 `two identical vials of a vaccine (i.e. from the same batch and the same manufacturer)`、`placed side by side on a flat surface` → **相符** | **必须降级**：`10–15 seconds` 不得保留为已核实内容（见 §2.5）。"并排比较沉降"可保留，粒度=句子级 |
| **D2d** | `:163` `similar or faster sedimentation indicates freeze damage and the batch must be discarded` | 判据部分 | **VERIFIED** | 判据原文见上（`similar or a faster rate … recorded as a "fail"`）→ 前半句 VERIFIED。**"the batch must be discarded" 是本文没有的规范结论**：论文结论为 `The shake test had 100% sensitivity, 100% specificity and 100% positive predictive value in this study, which confirms its validity for detecting freeze damage to aluminium-based freeze-sensitive vaccines.` —— 论文验证的是**检测有效性**，不给处置规则。处置语义须另找来源或标注为项目工程决策 | **前半 VERIFIED（句子级）；"batch must be discarded" 属项目决策，需标注** |

---

## 2. 必须降级或改写的项（含可直接粘贴的替换文本）

> 代码里字段是英文，以下替换文本一律英文、可直接粘贴。**本报告不修改任何已有代码或文档**，以下仅为建议文本。

### 2.1 `build_graph.py:137-145` — ICH 节点（本次核心）

**现状**（三个问题叠加：文档标题塞进 `clause`；`allowable excursion duration` 与 `MKT ceiling` 两个归属不成立；`verified` 仍是 `pending`）：

```
"clause_id": "R-ICH-Q1A",
"clause": "Stability testing of new drug substances and products",
"summary": "Basis for product-specific stability data (storage range, allowable excursion duration, MKT ceiling).",
"source_url": "https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf",
"verified": "pending A's W1 clause-level check",
```

**应改写为**：

```
"clause_id": "R-ICH-Q1A",
"clause": "ICH Q1A(R2) (document level; no clause cited)",
"summary": "Document-level basis for product-specific storage conditions: long-term testing at 5 °C +/- 3 °C for products intended for storage in a refrigerator (Q1A(R2) section 2.2.7.4) and at -20 °C +/- 5 °C for products intended for storage in a freezer (section 2.2.7.5), so that the shelf life and label storage statement derive from product stability data (sections 1.3, 2.2.9, 2.2.10). Q1A(R2) also defines mean kinetic temperature in its Glossary (Haynes formula), but states no MKT limit and no allowable excursion duration: excursions outside the label storage conditions must be evaluated using accelerated and, where appropriate, intermediate data (sections 2.1.7, 2.2.7.4). The allowable excursion duration and MKT ceiling used in this project are engineering parameters, not ICH requirements.",
"source_url": "https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf",
"verified": "2026-09-14 ICH official PDF, Q1A(R2) Current Step 4 version dated 6 February 2003 (24 pp). Document-level check only: section numbering confirmed (1, 2.1, 2.1.1-2.1.10, 2.2, 2.2.1-2.2.10, 3, 4); no clause titled 'Stability testing of new drug substances and products' exists - that string is the document title. Sections 2.2.7.4/2.2.7.5 and Glossary 'Mean kinetic temperature' verified verbatim. The node claims NO clause-level citation.",
```

如果希望保留一个**条款级**锚点（推荐，因为 `storage range` 确实可核到条款级），可另加一条独立节点：

```
"clause_id": "R-ICH-Q1A-2.2.7.4",
"title": "ICH Q1A(R2)",
"issuer": "ICH",
"clause": "Section 2.2.7.4 - Drug products intended for storage in a refrigerator",
"summary": "Long-term stability data at 5 °C +/- 3 °C (12 months) and accelerated data at 25 °C +/- 2 °C/60% RH +/- 5% RH (6 months); if significant change occurs within the first 3 months at the accelerated condition, a discussion should be provided to address the effect of short term excursions outside the label storage condition, e.g. during shipment and handling.",
"source_url": "https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf",
"verified": "2026-09-14 ICH official PDF, verbatim match (2.2.7.4)",
```

### 2.2 `build_graph.py:128-136` — HSA 节点

**现状**（`clause` 是自造描述；`source_url` 指向落地页而非指南本身；summary 窄于强制范围；`verified` 仍是 pending）：

```
"title": "HSA Guidance Notes on Good Distribution Practice (rev. 15 Dec 2023)",
"clause": "GDP standard for therapeutic products",
"summary": "Singapore's mandatory GDP standard for importers and wholesalers of therapeutic products, aligning storage, transport and temperature-control requirements.",
"verified": "document title/source confirmed 2026-09-10; clause-level wording pending A's W1 check",
```

**应改写为**：

```
"title": "HSA Guidance Notes on Good Distribution Practice (GUIDE-MQA-013-012, December 2023)",
"clause": "HSA GUIDE-MQA-013-012 (document level; sections 2.7, 2.8, 3.10 and Annex 1 'Cold chain products' apply)",
"summary": "Singapore's mandatory GDP standard for all local importers and wholesalers of Therapeutic Products, Chinese Proprietary Medicines, Cell, Tissue and Gene Therapy Products and Active Ingredients intended for the Singapore market. Covers storage (section 2.7: storage conditions per product label, continuous monitoring of temperature and humidity, recorded review), monitoring-device placement (section 2.8: located in areas most likely to show fluctuations and/or the hottest and coldest locations) and transport (section 3.10(d): secure and not subject to unacceptable degrees of heat, cold, light, moisture or other adverse influence). Annex 1 'Cold chain products' additionally requires label-based storage conditions, temperature mapping of cold rooms, continuous temperature recording, alarm system for temperature excursions with action and alert limits, backup power, temperature mapping or qualified/validated insulated containers for transport, and written procedures for handling temperature excursions.",
"source_url": "https://isomer-user-content.by.gov.sg/409/c19890a5-6658-492d-b8ff-1ec6e9dc9f9c/guide-mqa-013.pdf",
"verified": "2026-09-14 HSA official PDF, GUIDE-MQA-013-012, 21 pp, header 'DECEMBER 2023'; sections 2.7, 2.8, 3.10 and Annex 1 verified verbatim. Mandatory scope and the 15 December 2023 revision date are stated on the HSA landing page (https://www.hsa.gov.sg/therapeutic-products/manufacturing-import-wholesale/licence-to-manufacturer-import-or-wholesale/gmp-gdp/), not on the PDF itself. No clause-level citation is claimed.",
```

若需保留落地页作为并行来源，建议拆成两个字段（`landing_page_url` 与 `source_url`），**不要把落地页当作指南原文**。

### 2.3 `build_graph.py:105-106`（EU GDP 3.2.1）与 `:123-124`（EU GDP 9.4）— 修正 `verbatim` 标注

**现状**：`"verified": "2026-09-10 official OJ PDF, verbatim match (3.2.1)"`

**应改写为**（3.2.1）：

```
"verified": "2026-09-14 official OJ HTML text (CELEX 52013XC1123(01)), section 3.2.1 'Temperature and environment control' confirmed; summary is a paraphrase, not verbatim: the source reads 'monitoring devices are positioned in the areas that experience the extremes of fluctuations'.",
```

**应改写为**（9.4）：

```
"verified": "2026-09-14 official OJ HTML text (CELEX 52013XC1123(01)), section 9.4 'Products requiring special conditions' confirmed; summary is a paraphrase, not verbatim: the source reads 'For temperature-sensitive products, qualified equipment (e.g. thermal packaging, temperature-controlled containers or temperature-controlled vehicles) should be used ...'. Note section 9.4 also covers narcotics/psychotropic substances and highly active/radioactive materials, and separately requires temperature mapping under representative conditions accounting for seasonal variations.",
```

（`1.2` 的 `verbatim match` 标注本轮核对后**可以保留**：summary 与原文 (v)/(vi) 两子句实质等同，仅 `commonly known as 'CAPA'` 被省略。）

### 2.4 `build_graph.py:156-158`（CDC SOP）— 补一句本地化免责

**现状**：`verified` 已写 `2026-09-11 CDC Temperature Excursion Checklist (May 2014), steps quoted from the official PDF`（准确）。

**建议追加**（可直接粘贴到 `verified` 末尾，或作为独立字段）：

```
"Scope note: the checklist is written for the United States immunization programme context (references 'Immunization Program', 'Vaccines for Children (VFC) Program', 'state regulations for medical waste'); it is used in this project as a procedural template, not as a Singapore regulatory requirement."
```

### 2.5 `build_graph.py:160-166`（WHO shake test SOP）— **必改**：删掉 475/8 的证据归属错误与 10–15 秒

**现状**：

```
"summary": "... shake a suspect test vial and a deliberately frozen control vial of the same batch for 10–15 seconds and compare sedimentation side by side; similar or faster sedimentation indicates freeze damage and the batch must be discarded (WHO shake test, validated on 475 vials across 8 freeze-sensitive vaccine types).",
"source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC2908964/",
"verified": "2026-09-11 WHO shake-test validation study (PMC2908964) + WHO TRS 961 Annex 9 §6.9 official PDF (verified 2026-09-10)",
```

**应改写为**：

```
"summary": "Protect freeze-sensitive products from temperatures below 0 °C (WHO TRS 961 Annex 9 §6.9). On suspected freezing of an aluminium-adjuvanted vaccine: use two identical vials of the same batch and manufacturer - one deliberately frozen and thawed as the control, one the suspect test vial; hold both in one hand and shake, then place them side by side on a flat surface and compare sedimentation. Sedimentation that is similar to, or faster than, the frozen control is recorded as a 'fail' (freeze damage); slower sedimentation is a 'pass'. The validation study that established this reading reported 100% sensitivity, specificity and positive predictive value against phase-contrast microscopy (Kartoglu et al., Bull World Health Organ 2010;88:624-631). The shake duration is not specified in that study; decision times observed there ranged from 44 seconds to 20 minutes, with most products resolving in 1-5 minutes.",
"source_url": "https://europepmc.org/articles/PMC2908964?pdf=render",
"secondary_source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC2908964/",
"verified": "2026-09-14 Kartoglu U, Ozguler NK, Wolfson LJ, Kurzatkowski W. 'Validation of the shake test for detecting freeze damage to adsorbed vaccines', Bull World Health Organ 2010;88:624-631, doi:10.2471/BLT.08.056879 (PMID 20680128, PMCID PMC2908964), read in full via the Europe PMC mirror (8 pp). Verified verbatim: 'A total of 475 vials of 8 different types of World Health Organization prequalified freeze-sensitive vaccines from 10 different manufacturers were used.' UNVERIFIED: the figure '10-15 seconds' does not appear anywhere in the article and has been removed. The phrase 'the batch must be discarded' is this project's engineering disposition rule, not a statement of the cited study (the study validated detection, not disposal). The PMC URL cited previously returned a reCAPTCHA challenge in this session, not a 404.",
```

**同时建议**：把 `SOP-GDP-002` 的处置语义（`batch must be discarded`）与 WHO TRS 961 Annex 9 §6.9 拆开——上一轮已核实 §6.9 是**装箱防护要求**，不是报废规则（上一轮报告 §2.2 已要求改写，本轮不重复）。

### 2.6 建议新增的 ICH Q1E 节点（可选，但能补上"偏移须评估"的 ICH 侧依据）

```
"clause_id": "R-ICH-Q1E-2.5.1.2",
"title": "ICH Q1E",
"issuer": "ICH",
"clause": "Section 2.5.1.2 - Significant change at accelerated condition",
"summary": "For drug substances or products intended for storage in a refrigerator, where significant change occurs within the first 3 months at the accelerated storage condition, a discussion should be provided to address the effect of short-term excursions outside the label storage condition (e.g. during shipping or handling). Q1E gives numeric limits only for shelf-life extrapolation, not for allowable transport excursion duration.",
"source_url": "https://database.ich.org/sites/default/files/Q1E%20Guideline.pdf",
"verified": "2026-09-14 ICH official PDF, Q1E Current Step 4 version dated 6 February 2003 (19 pp), section 2.5.1.2 verified verbatim. Q1E contains no allowable excursion duration and no MKT limit.",
```

---

## 3. 可以直接确认的项（VERIFIED 及确切依据）

| 项 | 确切依据（全部本轮亲见原文） |
|---|---|
| **ICH Q1A(R2) 文档存在与版本** | ICH 官方 PDF（24 页），`Current Step 4 version dated 6 February 2003`；Document History 表记 `Q1A(R2) … 6 February 2003`；官方页 `ich.org/page/quality-guidelines` 记 `Date of Step 4: 6 February 2003；Status: Step 5` |
| **Q1A(R2) 结构** | `1. INTRODUCTION`（1.1 Objectives / 1.2 Scope / 1.3 General Principles）、`2. GUIDELINES`（2.1 Drug Substance 2.1.1–2.1.10；2.2 Drug Product 2.2.1–2.2.10）、`3. GLOSSARY`、`4. REFERENCES`；**有 2.1/2.2/2.3 式三级编号**（如 2.1.7.1、2.2.7.4） |
| **Q1A(R2) → `storage range`** | §2.1.7.2 冷藏 `5°C ± 3°C`；§2.1.7.3 冷冻 `- 20°C ± 5°C`；§2.2.7.4 冷藏 `5°C ± 3°C`；§2.2.7.5 冷冻 `- 20°C ± 5°C`；§2.1.7.4/§2.2.7.6 `below -20°C … case-by-case`；§1.3、§2.2.10 标签储存声明须基于稳定性 |
| **Q1A(R2) → MKT 定义（非上限）** | Glossary `Mean kinetic temperature`（Arrhenius、Haynes 公式、`higher than the arithmetic mean`）；无任何阈值 |
| **Q1A(R2) → 偏移"须评估"（非时长上限）** | §2.1.7 `evaluate the effect of short term excursions outside the label storage conditions (such as might occur during shipping)`；§2.2.7.4 同义；Glossary `Storage condition tolerances` `Excursions that exceed the defined tolerances for more than 24 hours should be described in the study report and their effect assessed` |
| **ICH Q1E 存在与内容（新增核实）** | ICH 官方 PDF（19 页），`Current Step 4 version dated 6 February 2003`；§2.5.1.2 冷藏产品偏移讨论要求；§2.5.1.1/§2.5.1.2 外推上限（`X + 3 months`、`up to 1.5X … X + 6 months`）——**是货架期上限，不是偏移上限** |
| **HSA GDP 指南存在与版本** | 官方 PDF `guide-mqa-013.pdf`，21 页，页眉 `GUIDANCE NOTES ON GOOD DISTRIBUTION PRACTICE DECEMBER 2023`，编号 `GUIDE-MQA-013-012`；HSA 落地页称 `revised on 15 December 2023` |
| **HSA GDP 强制性与适用主体** | 落地页 `mandatory for all local importers and wholesalers of Therapeutic Products, Chinese Proprietary Medicines, Cell, Tissue and Gene Therapy Products and Active Ingredients intended for the Singapore market`；`GDP auditors will conduct audits … prior to the issuance of local dealer's licences` |
| **HSA GDP 覆盖 storage/transport/temperature** | §2.7、§2.8、§3.10(d)、Annex 1（16 条，含温度制图、连续记录、偏移报警、备用电源、运输温度制图/验证箱、偏移处理程序）；词汇表 `Cold Chain Products = Products requiring storage condition of not more than 8°C` |
| **EU GDP §1.2** | 原文 (v)/(vi)：`deviations from established procedures are documented and investigated`；`appropriate corrective and preventive actions (commonly known as 'CAPA') are taken to correct deviations and prevent them in line with the principles of quality risk management` |
| **EU GDP §3.2.1** | 原文：`An initial temperature mapping exercise should be carried out on the storage area before use, under representative conditions. Temperature monitoring equipment should be located according to the results of the mapping exercise, ensuring that monitoring devices are positioned in the areas that experience the extremes of fluctuations. The mapping exercise should be repeated according to the results of a risk assessment exercise or whenever significant modifications are made to the facility or the temperature controlling equipment.` |
| **EU GDP §9.4** | 原文：`For temperature-sensitive products, qualified equipment (e.g. thermal packaging, temperature-controlled containers or temperature-controlled vehicles) should be used to ensure correct transport conditions are maintained between the manufacturer, wholesale distributor and customer.` |
| **CDC 清单** | 1 页 PDF，`CDC's Temperature Excursion Checklist`，页脚 `May 2014`，三个板块与全部步骤逐条对得上 |
| **Kartoglu 2010 shake test 研究身份与数字** | `Bull World Health Organ 2010;88:624–631`，`doi:10.2471/BLT.08.056879`，WHO 作者；`480 → 475 vials`、`8 types`、`10 manufacturers`、`319 non-frozen / 156 frozen`、灵敏度/特异度/阳性预测值均 100% |
| **Q1A(R2) 在新加坡的实施** | ICH 官方页：`HSA, Singapore - Implemented; Date: 1 January 2008; Reference: ASEAN Common Technical Dossier (ACTD) for the registration of pharmaceuticals for human use, Part II: Quality` |

---

## 4. 给项目的一句话结论

**ICH 与 HSA 两个节点都可以留在正式报告里，但都必须降级为"文档级"改写，且 ICH 节点的两个归属必须删除**：ICH Q1A(R2) 的 PDF 真实、版本（2003-02-06）与 `storage range` 归属**经得起条款级核实**（§2.2.7.4/§2.2.7.5），但 `clause` 字段现在写的 `"Stability testing of new drug substances and products"` 是**文档标题而非条款**，而 `summary` 里的 `allowable excursion duration` 与 `MKT ceiling` 两项归属**在 Q1A(R2) 中不成立**（前者全文无此概念，后者只有 MKT 定义、没有任何上限）——这两项**必须移出 ICH 归属、改标为本项目工程参数**，若要保留 ICH 侧依据，请改引本轮已一手核实的 **ICH Q1E §2.5.1.2**（但 Q1E 也只要求"讨论偏移影响"，仍不给时长上限）；HSA 节点的 `rev. 15 Dec 2023` **属实**（依据是 HSA 落地页声明，PDF 只写 `DECEMBER 2023`）、强制性与 storage/transport/temperature 覆盖**也属实**，但 `clause` 字段 `"GDP standard for therapeutic products"` 是自造描述、且 `source_url` 指向落地页而非指南原文，**必须改为指南 PDF（GUIDE-MQA-013-012）并补上文档级标识**。此外必须立即修正的两处引用卫生问题：EU GDP 3.2.1/9.4 的 `verbatim match` 标注实为**意译**（章节号本身正确），以及 SOP-GDP-002 里的 **`475 vials / 8 types` 属实但 `10–15 seconds` 在原文中不存在，必须删除或标 UNVERIFIED**。

---

## 5. 实际访问过的 URL 清单

**成功取得内容（均经 `r.jina.ai` 抽取）**

| URL | 状态 | 用途 |
|---|---|---|
| `https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf` | 200（24 页全文） | **本次核心**：Q1A(R2) 标题页、Document History、目录结构、§2.1.7/§2.2.7/Glossary/§2.2.10 原文 |
| `https://database.ich.org/sites/default/files/Q1E%20Guideline.pdf` | 200（19 页全文） | ICH Q1E 一手核实（§2.5.1.2、Appendix A） |
| `https://www.ich.org/page/quality-guidelines` | 200 | Q1A(R2)/Q1E 官方定位、Step 4 日期、Step 5 状态、HSA 实施记录、Q1 合并修订中（Step 3, 2025-04-11） |
| `https://www.hsa.gov.sg/therapeutic-products/manufacturing-import-wholesale/licence-to-manufacturer-import-or-wholesale/gmp-gdp/` | 200 | HSA 落地页：GDP 强制性声明、**`revised on 15 December 2023`**、指南 PDF 链接 |
| `https://isomer-user-content.by.gov.sg/409/c19890a5-6658-492d-b8ff-1ec6e9dc9f9c/guide-mqa-013.pdf` | 200（21 页全文） | HSA GDP 指南原文：§2.7/§2.8/§3.10、Annex 1 COLD CHAIN、词汇表 |
| `https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:52013XC1123(01)` | 200（全文） | EU GDP §1.2、§3.2.1、§3.3、§9.1–9.4 原文 |
| `https://stacks.cdc.gov/view/cdc/142711/cdc_142711_DS1.pdf` | 200（1 页） | CDC Temperature Excursion Checklist（May 2014）全文 |
| `https://europepmc.org/articles/PMC2908964?pdf=render` | 200（8 页全文） | Kartoglu 2010 shake test 验证研究全文（475/8、判据、决策时间、无秒数） |
| `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=TITLE:"Validation of the shake test…"&resultType=core` | 200（JSON） | 文章身份交叉校验：PMID 20680128 / PMCID PMC2908964 / doi 10.2471/blt.08.056879 / 88(8):624-631 |
| `https://europepmc.org/article/PMC/PMC2908964` | 200 | 同一文章摘要（与 PDF 全文互校） |

**失败 / 受阻（如实记录）**

| URL | 状态 / 障碍 | 影响 |
|---|---|---|
| `https://pmc.ncbi.nlm.nih.gov/articles/PMC2908964/`（**代码当前所引**） | **反爬拦截**：经代理返回 `Checking your browser - reCAPTCHA`、`Warning: This page maybe requiring CAPTCHA`（**非 404、非付费墙**） | 代码所引域名的既有 URL 在本会话不可直接读取；已用 Europe PMC 同一 PMCID 镜像完成核实。**URL 本身并未失效**（对普通浏览器应可打开），但建议代码同时给出镜像地址 |
| `https://europepmc.org/article/MED/20573151` | 200，但**内容完全无关**（是 acupuncture for induction of labour 一文，PMID 20573151） | 我原先用于定位的 PMID 猜测错误，已改用 Europe PMC 检索 API 定位到正确记录；**未采信任何来自该页的内容** |
| `https://scielosp.org/article/bwho/2010.v88n8/624-631/en/` | **HTTP 403** + `Challenge Loading` / Bunny Shield 反爬 | 未能经此取得全文（已由 Europe PMC 替代） |
| `https://www.scienceopen.com/document?vid=91d161af-…` | 反爬：`Performing security verification` / `Just a moment...` | 未取得内容 |
| `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC2908964/fullTextXML` | **HTTP 422** + `Unexpected empty file` | 该文不在 Europe PMC 全文XML 索引中（`inEPMC: "Y"` 但非 OA 子集）；改用 `?pdf=render` 成功 |
| `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC2908964/supplementaryFiles` | 200 但返回 `Article with id PMC2908964 is not open access one` | 确认该文**不在 OA 子集**（`isOpenAccess: "N"`），故 XML 接口不可用 |
| `https://iris.who.int/handle/10665/270736` | 200 但**正文为空**（仅 "DSpace" 标题，页面未完整加载） | 未能经 WHO IRIS 取得该文；**该 handle 内容未被采信**（上一轮报告曾把它列为候选，本轮仍未能核实该 handle 指向何物） |
| `https://iris.who.int/bitstream/handle/10665/64776/WHO_EPI_LHIS_98.02.pdf?sequence=1`（搜索结果中出现） | **未访问**（仅在搜索结果中见到链接文本） | 未采信 |
| `https://www.who.int/vaccines-documents/DocsPDF06/847.pdf`（论文内引用的 `Shake test learning guide`，pages 59–62） | **未访问**：该文档由论文正文以 `http://` 引用，我未在任何检索中获得其可解析的现行地址 | **这是 `10–15 seconds` 唯一可能的原始出处，本轮未能一手核实 → 该数字判定 UNVERIFIED 并要求删除。不得用搜索结果摘要或第三方转载（如各国卫生部小册子）替代** |
| `https://slma.lk/wp-content/uploads/2015/01/SLMA-GUIDELINES-INFORMATION-ON-VACCINES-BOOK.pdf`（搜索结果中出现，含 shake test 段落） | **HTTP 404**（`Page not found`） | 未取得；且即便取得也属**二手**，不足为据 |
| `https://www.ich.org/page/quality-guidelines` 直连 | 200 但输出被截断（`Content truncated`，另有 50,642 字节未显示） | **Q1E 之后的内容（Q7 以后）未读到**；本报告只引用截断前可见的 Q1A–Q1E 段落，未对未读到部分作任何陈述 |

**方法声明**：本报告不存在任何以"搜索结果摘要"充当原文核实的情形；所有 `UNVERIFIED` 项均因**未能亲见原文**而标记，而非因检索不到信息而标记。
