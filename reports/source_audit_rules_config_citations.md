# 冷链药品合规来源核实报告（`src/rule_engine/rules_config.json`）

核实对象：`src/rule_engine/rules_config.json` 中 `_note` 与 `_sources` 声称的法规/标准引用。
核实方法：web 检索 + 抓取原始文件；**逐条**判断引用对象是否真实存在、以及是否真的支持被归属的主张。

## 0. 方法与限制（先声明，避免误读）

- `web_fetch` 不接受 `application/pdf`（返回 `unsupported content type "application/pdf"`），且本会话沙箱内 shell 直连网络被拒（`curl: (35) schannel: SEC_E_NO_CREDENTIALS`）。因此**PDF 原文通过 `r.jina.ai` 文本抽取代理获取**，抽取结果即本文证据来源；引用片段均出自该抽取文本。
- 抽取可信度交叉校验：WHO 官方落地页标注该 Annex "Number of pages 49"，抽取值亦报告 `Number of Pages: 49`；落地页 Overview 文字与抽取正文的 Background 段落逐字一致。Levemir 标签抽取报告 76 页、Merilog 41 页，与其"专业说明书 + 患者说明书/IFU"结构相符。
- 判定分级：`VERIFIED` = 见到原始文件且条款内容与主张相符；`PARTIAL` = 文件真实但条款号对不上，或只能核到文档级/仅二手来源；`UNVERIFIED` = 找不到或打不开原始文件；`CONTRADICTED` = 见到原始文件且与主张矛盾（含"归属不成立：全文无此内容"）。
- 本次所有引用中，**无一项**是通过"搜索结果摘要"顶替原文核实的。

---

## 1. 逐条判定表

| # | 引用对象 | 被引条款号 | 判定 | 证据 / 原文片段 | 实际可用粒度 |
|---|---|---|---|---|---|
| 1 | WHO TRS 961 Annex 9（承载："铝佐剂疫苗 +2~+8 °C、勿冻结"） | 无（文档级） | **CONTRADICTED** | 已通读该 Annex 全文（49 页）。全文**无** `+2 to +8`、`2 °C to 8 °C`、`aluminium`/`aluminum adjuvant`、`shake test` 任何字样。文档定位是通用 TTSPP 储存运输模型指南，从不给出 +2~+8 °C 的疫苗储存范围 | 文档级——文档存在，但**内容不支持**该归属 |
| 2 | WHO TRS 961 Annex 9 | **§6.2** | **VERIFIED** | §6.2 标题 = `Product stability profiles`。正文原句："Transport TTSPPs in such a manner that transport temperatures meet local regulatory requirements … and/or so that temperature excursions above or below the manufacturer's labelled storage temperature range do not adversely affect product quality. **Product stability data must demonstrate the acceptable temperature excursion time during transport.**" | **条款级** |
| 3 | WHO TRS 961 Annex 9（承载：`freeze_sensitive && temp <= 0 → scrap` 冻结报废规则） | **§6.9** | **CONTRADICTED** | §6.9 标题 = `Shipping container packing`（属第 6 章"运输与交付"）。正文仅要求装箱时 "protect **freeze-sensitive products against temperatures below 0 °C** when frozen packs are used"——是**装箱防护要求**，不是报废/处置规则。全文无任何 `temp ≤ 0 → scrap` 式自动报废条款 | **条款级**：编号成立，但该条款不是报废规则。（真正涉及报废的是 §8.6.1 "Quarantine returned TTSPPs that have been exposed to unacceptable storage and/or transport temperatures and mark for disposal" 与 §8.6.3 `Disposal procedures`，且均为"评估后处置"而非自动报废） |
| 4 | EU GDP 2013/C 343/01（承载："运输包装完整性原则"） | 文档 + §9.2 | **VERIFIED** | 结构为 CHAPTER 1–11，节号形如 `9.2.`。§9.2 `Transportation` 原句："It is the responsibility of the wholesale distributor to ensure that vehicles and equipment used to distribute, store or handle medicinal products are suitable for their use and appropriately equipped to prevent exposure of the products to conditions that could affect **their quality and packaging integrity**."；§9.3 `Containers, packaging and labelling` 另有 "transported in containers that have no adverse effect on the quality of the products, and that offer adequate protection from external influences" | **条款级** |
| 5 | EU GDP 2013/C 343/01 | **§9.2** | **VERIFIED** | §9.2 `Transportation` 原句："If a **deviation such as temperature excursion** or product damage has occurred during transportation, this **should be reported to the distributor and recipient** of the affected medicinal products. **A procedure should also be in place for investigating and handling temperature excursions.**"；同节首段另有 "The required storage conditions … should be maintained during transportation within the defined limits as described by the manufacturers or on the outer packaging." | **条款级**（同时支持"须上报 + 须调查处理"与"须维持在标签范围内"两条主张） |
| 6 | USP〈1079〉（承载："MKT 的定义"） | `〈1079〉` | **PARTIAL** | MKT 定义确实存在于 USP，但在 **〈1079.2〉**§3：`MKT is the single calculated temperature at which the total amount of degradation over a particular period is equal to the sum of the individual degradations that would occur at various temperatures. … It is not a simple arithmetic mean.` 另：〈1079.2〉正文把 **〈1079〉** 称为 `Risks and Mitigation Strategies for the Storage and Transportation of Finished Drug Products`，即 MKT 不在 〈1079〉 本体 | **章节级**——标准真实、**章节号错**（应写 〈1079.2〉；〈1079〉/〈1079.2〉/〈1079.3〉 同属 〈1079〉 系列） |
| 7 | USP〈1079〉（承载："freezer 档 −25~−10 °C"） | `〈1079〉` | **UNVERIFIED** | 〈1079.2〉 公开预发布文本的 Table 1 只列三类档位：`CCT 2°–8°`、`CRT 20°–25°`、`Room temperature in climatic zone IVb 15°–30°`——**无 freezer 档，无 −25、无 −10 任何数字**；该章节反而指向 "MKT is referenced in the controlled room temperature (CRT) and controlled cold temperature (CCT) definitions in **Packaging and Storage Requirements 〈659〉**"。而 〈659〉 为付费标准：`https://doi.usp.org/USPNF/USPNF_M2773_06_01.html` 仅给出 INTRODUCTION 一段预览 + 订阅提示 | **障碍：付费墙**。未能见到任何一手 USP 文本含 "−25 to −10"。（另注：`frozen_m20` 的 `refs` 为空数组，该项**原本就没有任何引用**） |
| 8 | FDA 说明书 LEVEMIR（insulin detemir，NDA 021536） | §16.2 Storage | **VERIFIED** | 原始 PDF = `accessdata.fda.gov/drugsatfda_docs/label/2022/021536s060lbl.pdf`，Revised 07/2022，Novo Nordisk。§16.2：`Store unused (unopened) LEVEMIR in the refrigerator between 36° to 46°F (2° and 8°C). Do not store in the freezer … **Do not freeze. Do not use LEVEMIR if it has been frozen.**`（患者说明书中重复出现） | **章节级**（§16.2 Storage）——完整支持"未开封 2–8 °C / 勿冻结 / 冻结即弃用" |
| 9 | FDA 说明书 MERILOG（insulin aspart-szjj，BLA 761325） | Instructions for Use | **VERIFIED** | 原始 PDF = `accessdata.fda.gov/drugsatfda_docs/label/2025/761325Orig1s000lbl.pdf`，Approved February 2025，Sanofi。`Store unused MERILOG vials in the refrigerator between 36°F to 46°F (2°C to 8°C). **Do not freeze MERILOG.** … **If a vial has been frozen or overheated, throw it away.**`；笔档同义（`Do not use MERILOG if it has been frozen.`） | **说明书章节级**——完整支持同一主张 |
| 10 | 说明书中的 **glargine / lispro** | 无 | **UNVERIFIED** | 被引的两个 URL 分别是 NDA 021536（Levemir/insulin detemir）与 BLA 761325（Merilog/insulin aspart-szjj），**均不覆盖 glargine 与 lispro**；config 未给出任何对应来源 | **未覆盖**——主张的产品清单宽于引用覆盖范围（4 个产品名只核到 2 个） |
| 11 | Pfizer-BioNTech（承载："超低温 −80~−60 °C"） | FDA 2021-02-25 | **VERIFIED（内容）** | 一手 FDA 新闻稿 *Coronavirus (COVID-19) Update: FDA Allows More Flexible Storage, Transportation Conditions for Pfizer-BioNTech COVID-19 Vaccine*（2021-02-25），原文："This reflects an alternative to the preferred storage of the undiluted vials in an ultra-low temperature freezer **between -80ºC to -60ºC** (-112ºF to -76ºF)." | **句子级**。**但** config 所引 URL 本身已 404（见 #12）；且该范围为 2021 年原始剂型，**与现售 Comirnaty（DailyMed 更新至 2026-09-02，2026-2027 配方）的 2–8 °C 冷藏体系不同**，报告若不分年代会误导 |
| 12 | config 引用的 `https://www.fda.gov/media/144413/download` | — | **UNVERIFIED** | 抓取返回 **HTTP 404 / "Page Not Found"**（经代理与直连两次一致）。该 URL 在 2021 年**确实**是 EUA `Fact Sheet for Healthcare Providers Administering Vaccine` 的地址——2021-02-25 FDA 新闻稿的 Related Information 正指向它，故属**引用失效**而非凭空捏造 | URL 已不可解析 |
| 13 | Pfizer 多级稳定性窗口（"2–8 °C ≤1 月 / −20 °C ≤2 周 / 室温数小时，FDA 2021-05"） | FDA 2021-05 | **PARTIAL** | ①"室温数小时"：一手 FDA 2021-02-25 新闻稿支持（"storage of thawed vials **after dilution** … can be held at refrigerator temperature or **room temperature for use within 6 hours**"）——即 **6 小时**，且限定"稀释后"。②"2–8 °C 1 个月"：FDA 2021-05 的一手页面现为 404，仅**二手**复述可证（Iowa IDPH 公报 2021-05-20；香港卫生署药物办公室新闻转载）。③"−20 °C 2 周"：被引公报写作 "−20 °C"，而 FDA 自家材料只说 "pharmaceutical freezer / standard freezer temperature"，fact sheet 档位为 **−25 °C to −15 °C**，"−20 °C" 是公报的四舍五入 | 一手仅到**句子级且只覆盖"室温 6 小时"**；"1 个月"与"−20 °C"仅二手/近似 |
| 14 | `content.govdelivery.com/accounts/IACIO/bulletins/2da52d5` | — | **PARTIAL** | URL 可打开（HTTP 200），但**不是 FDA 文件**：是 **Iowa Department of Public Health**（州卫生部门）2021-05-20 通讯。其原文："Ultra-Cold (**-70**)"、"vials may remain frozen at **-20 ºC for up to 2 weeks**"、"may remain at 2 ºC - 8 ºC for **1 month**"、"Total storage time … should not exceed 45 days" | **二手/三手来源**——可作旁证，不能作为法规归属 |
| 15 | `sciencedirect.com/…/S0264410X18313896` | — | **UNVERIFIED** | 抓取返回 **HTTP 403** + "Are you a robot?" captcha + 订阅墙，**未亲见原文**。搜索结果链接文本提示其标题为 *Physical and chemical changes in Alhydrogel™ damaged by freezing*（Vaccine）——此标题来自搜索结果，**未经我原文确认**，不得当作已核实 | 无法核到；且即便核实，它也是**研究论文（二手文献）**，不是规范性来源 |

---

## 2. 必须降级的引用（含应改写成什么）

1. **「WHO TRS 961 Annex 9 → 铝佐剂疫苗 +2~+8 °C、勿冻结」→ 删除该归属。**
   改写成：「2–8 °C 冷藏与冻敏性为**类别原型设定**，来源待补」；或改引真正承载该主张的 WHO 疫苗冷链文件（本次**未**逐条核实，仅列出候选：WHO IRIS *Validation of the shake test for detecting freeze damage to adsorbed vaccines*，handle 10665/270736）。**不要**再写成 Annex 9。

2. **「WHO TRS 961 Annex 9 §6.9 → 冻结报废规则」→ 条款号指向错误，必须改写。**
   可保留的写法：「§6.9 `Shipping container packing`：装箱须保护冻敏产品免于 0 °C 以下（"protect freeze-sensitive products against temperatures below 0 °C when frozen packs are used"）」。
   报废部分改写为：「`temp ≤ 0 → scrap` 是**本项目工程规则**，非 WHO 条款；WHO 中相近表述为 §8.6.1（"mark for disposal"）与 §8.6.3 `Disposal procedures`，均以评估为前提」。

3. **「WHO TRS 961 Annex 9 §6.2 → 偏移须短促」→ 只保留"由稳定性数据决定"这半句。**
   改写成：「§6.2 `Product stability profiles`：偏移时长必须由产品稳定性数据证明（`Product stability data must demonstrate the acceptable temperature excursion time during transport`）」。"**须短促**"在 §6.2 无原文依据（"须评估"的真实落点是 §8.2.2："All unacceptable temperature excursions should be evaluated to determine their effect on the product"）。

4. **「USP〈1079〉MKT 定义」→ 章节号改为〈1079.2〉。**
   改写成：「USP〈1079.2〉`Mean Kinetic Temperature in the Evaluation of Temperature Excursions During Storage and Transportation of Drug Products`（PF 49(2) 预发布文本，©2024 USPC）」。注意该文本带 `Change to read` 与 `(USP 1-Aug-2025)` 标记，属**预发布/修订中**状态，引用时应标注为 PF 预发布而非最终官方章节。

5. **「USP〈1079〉freezer 档 −25~−10 °C」→ 改为 UNVERIFIED 或彻底去掉 USP 归属。**
   改写成：「`frozen_m20` 为 −25~−15 °C 工程原型区间，**无已核实标准来源**（USP〈659〉为付费标准，本次未能取得原文；〈1079.2〉无 freezer 档）」。**不要**写 "USP〈1079〉freezer 档为 −25~−10 °C"。（`refs: []` 已隐含此点，但 `_sources` 文字把 USP 写了进去，须一并改）

6. **胰岛素产品清单 → 缩到已核范围，或补齐来源。**
   改写成：「未开封 2–8 °C 冷藏、勿冻结、冻结即弃用（FDA 说明书：**Levemir** §16.2 Storage；**Merilog** Instructions for Use）」。若要保留 glargine / lispro，须补引其各自标签（如 NDA 021081 / NDA 020563），否则删除这两个产品名。

7. **「Pfizer EUA `fda.gov/media/144413/download`」→ 换 URL 并标注年代。**
   改写成：「−80~−60 °C 超低温（FDA 新闻稿 2021-02-25，*FDA Allows More Flexible Storage, Transportation Conditions for Pfizer-BioNTech COVID-19 Vaccine*）」，并**明确注明**：该条件属 2021 年原始剂型，**现售 Comirnaty 为 2–8 °C 冷藏体系**，不可作为当前 mRNA 产品储存依据。原 `media/144413/download` 已 404，须替换或标注"仅存档可得"。

8. **「多级窗口 FDA 2021-05」→ 拆分标注一手/二手。**
   改写成：「室温 6 小时（稀释后）：FDA 新闻稿 2021-02-25（一手）；2–8 °C 至多 1 个月：据 Iowa IDPH 公报 2021-05-20（**二手**，FDA 一手页面已 404）；−20 °C 2 周：据同一公报，**FDA 原文档位为 −25 °C 至 −15 °C**」。

9. **ScienceDirect 论文 → 标为"二手文献、内容未核实"。**
   改写成：「Alhydrogel 冻融损伤为研究文献所述（Vaccine 期刊论文，**内容未核实/付费墙**）」，且不得作为规范性依据。

---

## 3. 可以直接确认的引用

| 引用 | 确切依据（一手/条款级） |
|---|---|
| **EU GDP 2013/C 343/01 §9.2** | 《Guidelines of 5 November 2013 on Good Distribution Practice of medicinal products for human use》，OJ C 343/1, 23.11.2013（CELEX 52013XC1123(01)）；§9.2 `Transportation` 明文要求偏移**上报**给配送方与收货方、并**建立调查与处理程序**；同节要求运输中须维持在厂家/外包装标示范围内 → **支持"偏移须上报评估"与"维持在标签范围内"** |
| **EU GDP 2013/C 343/01（运输包装完整性）** | 同文件 §9.2 "…conditions that could affect their quality **and packaging integrity**" + §9.3 `Containers, packaging and labelling` → **支持"运输包装完整性原则"** |
| **WHO TRS 961 Annex 9 §6.2** | WHO Technical Report Series No. 961, 2011, Annex 9（49 页，2011-08-02 发布）；§6.2 `Product stability profiles` 原句要求**稳定性数据证明可接受的运输偏移时长** → **支持"偏移时长由稳定性数据决定"** |
| **FDA Levemir（021536s060lbl）§16.2** | Revised 07/2022，Novo Nordisk；"Store unused (unopened) LEVEMIR in the refrigerator between … (2° and 8°C). Do not freeze. **Do not use LEVEMIR if it has been frozen.**" → **支持"未开封 2–8 °C / 勿冻结 / 冻结即弃用"** |
| **FDA Merilog（761325Orig1s000lbl）** | Approved February 2025，Sanofi；"Store unused MERILOG vials in the refrigerator between … (2°C to 8°C). Do not freeze MERILOG. **If a vial has been frozen or overheated, throw it away.**" → **支持同一主张** |
| **Pfizer −80~−60 °C** | FDA 新闻稿 2021-02-25："the preferred storage of the undiluted vials in an **ultra-low temperature freezer between -80ºC to -60ºC**"（经加拿大政府网页存档取得）→ **支持 −80~−60 °C** |
| **USP MKT 定义（章节号除外）** | USP〈**1079.2**〉（PF 49(2) 公开预发布文本）§3 给出 MKT 的完整定义与 Arrhenius 公式 → **支持"MKT 为时间加权/虚拟等效温度、非算术平均"这一内涵**，但引用必须改号 |

> 附带事实（可用于报告正当性，但**不能**反过来说 USP 支持本项目构造）：USP〈1079.2〉Table 1 对 CCT（2–8 °C）给出的公开允许值是 **MKT ≤ 8 °C、时间周期 24 h、可接受偏移区间 8–15 °C、最高不超过 15 °C**。本项目对 2–8 °C 类别取的 `mkt_threshold_c = 10 °C`、`allowable_duration_min = 30 min` **远比 USP 公开档位保守**；但 "mkt = 标签上限 + 容差" 这一构造**并非** USP 的方法（USP 给的是分档 MKT 上限与最长偏移时间），config 自身也已声明其为工程取值——该声明是准确的，应保留并加强。

---

## 4. 给项目的一句话结论

**能进正式报告的**：EU GDP 2013/C 343/01 §9.2（及 §9.3 的包装完整性）、WHO TRS 961 Annex 9 §6.2、FDA Levemir §16.2 与 Merilog 说明书的储存条款、FDA 2021-02-25 的 "−80~−60 °C"（须换掉 404 的 URL 并注明配方年代）、以及 USP MKT 定义——**但必须把〈1079〉改成〈1079.2〉**；**其余只能作为工程假设声明**：`allowable_duration_min`、`mkt_threshold_c`（含"标签上限 + 容差"构造）、`temp ≤ 0 → scrap` 自动报废规则、USP −25~−10 °C 的 freezer 档归属、以及 glargine/lispro 的覆盖；**必须删除或明确降级为二手**的是"WHO Annex 9 承载 +2~+8 铝佐剂储存范围"与"§6.9 冻结报废规则"这两条归属，以及"多级窗口 = FDA 2021-05 一手"的表述。

---

## 5. 实际访问过的 URL 清单

**成功取得内容**

| URL | 状态 | 用途 |
|---|---|---|
| `https://cdn.who.int/media/docs/default-source/medicines/norms-and-standards/guidelines/inspections/trs961-annex9-modelguidanceforstoragetransport.pdf`（经 `r.jina.ai` 抽取） | 200（抽取成功，49 页全文） | WHO Annex 9 全文、§6.2/§6.9 章节与原文 |
| `https://www.who.int/publications/m/item/trs961-annex9-modelguidanceforstoragetransport` | 200 | WHO 官方落地页：标题、TRS No.961/2011、49 页、Overview（用于交叉校验） |
| `https://r.jina.ai/https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:52013XC1123(01)` | 200 | EU GDP 2013/C 343/01 全文（§9.1–§9.4 原文） |
| `https://www.accessdata.fda.gov/drugsatfda_docs/label/2022/021536s060lbl.pdf`（经代理） | 200（76 页） | LEVEMIR 标签 §16.2 Storage |
| `https://www.accessdata.fda.gov/drugsatfda_docs/label/2025/761325Orig1s000lbl.pdf`（经代理） | 200（41 页） | MERILOG 标签 / Instructions for Use |
| `https://www.uspnf.com/sites/default/files/usp_pdf/EN/USPNF/usp-nf-notices/PF492_M13855.pdf`（经代理） | 200（4 页） | USP〈1079.2〉MKT 定义与 Table 1 |
| `https://doi.usp.org/USPNF/USPNF_M2773_06_01.html` | 200 | USP〈659〉**付费预览**（仅 INTRODUCTION），用于说明 freezer 档无法核实的障碍 |
| `http://content.govdelivery.com/accounts/IACIO/bulletins/2da52d5` | 200 | 识别为 Iowa Department of Public Health 公报（二手） |
| `https://webarchiveweb.wayback.bac-lac.canada.ca/web/20210310223840/https://www.fda.gov/news-events/press-announcements/coronavirus-covid-19-update-fda-allows-more-flexible-storage-transportation-conditions-pfizer` | 200 | FDA 2021-02-25 新闻稿存档（−80~−60 °C、室温 6 小时） |
| `https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=48c86164-de07-4041-b9dc-f2b5744714e5` | 200 | 现售 COMIRNATY 标签（2026-2027 配方，2–8 °C 体系），用于年代差异说明 |

**失败 / 受阻（如实记录）**

| URL | 状态 / 障碍 | 影响 |
|---|---|---|
| `https://www.fda.gov/media/144413/download` | **HTTP 404**（代理与直连各一次，均 Page Not Found） | config 的 Pfizer 引用 URL 失效 |
| `https://www.fda.gov/media/153715/download` | **HTTP 404** | 另一 EUA fact sheet 链接亦失效 |
| `https://www.fda.gov/news-events/press-announcements/fda-brief-fda-authorizes-longer-time-refrigerator-storage-thawed-pfizer-biontech-covid-19-vaccine` | **HTTP 404** | 2021-05 "1 个月" 的一手 FDA 页面不可达 |
| `https://www.sciencedirect.com/science/article/abs/pii/S0264410X18313896` | **HTTP 403** + captcha + 订阅墙（直连与代理均失败） | 无法核实该文献内容 |
| `https://r.jina.ai/https://web.archive.org/…/fda.gov/media/144413/download` | **HTTP 403**（代理侧对 web.archive.org 的匿名访问封禁，`AbuseAlleviationError`，封禁期至 2026-09-13） | 无法用 Wayback 取 2021 年 fact sheet 原文 |
| `https://webarchiveweb.wayback.bac-lac.canada.ca/web/20210310223840/https://www.fda.gov/media/144413/download` | 存档侧**限流**（"You've reached the limit for the number of requests"，多次重试仍受限） | 未能取到 EUA fact sheet 本身的档位表；该表内容仅由 FDA 新闻稿与二手公报间接支持 |
| `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52013XC1123(01)`（直连） | HTTP 202 空响应（反爬），改由代理取得 | 已绕过，不影响结论 |
| `https://cdn.who.int/…/trs961-annex9….pdf`、`accessdata.fda.gov/…pdf`（`Invoke-WebRequest` / `curl.exe` 直连） | `schannel: SEC_E_NO_CREDENTIALS`（沙箱内 TLS 凭证不可用） | 改用 `r.jina.ai` 抽取代理；已在第 0 节声明 |
