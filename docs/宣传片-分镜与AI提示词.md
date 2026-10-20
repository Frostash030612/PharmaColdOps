# 宣传片（5 分钟）分镜、AI 空镜提示词与口播稿

> 对应课程要求：briefing v2.17 p9「A 5-minute video clip to promote/sell your system/solution, covering: Business Pain & Value; Use Case Demo」。
> 交付命名：`IRS-PM-<YYYY-MM-DD>-<class>-GRP-<组名>-PharmaColdOps-promotion.mp4`。
> 本文件只解决**画面素材**与**口播口径**，不含真实录屏脚本（录屏走 `docs/完整演示与端到端验收.md`）。

---

## 0. 先看红线（决定 AI 能做什么、不能做什么）

| # | 红线 | 依据 | 对本片的约束 |
|---|---|---|---|
| 1 | **禁止 AI 生成演讲语音** | briefing v2.17 p13 评分项 5 | 所有旁白由组员本人录；AI 视频即使自带音频也要**静音/删除** |
| 2 | Demo 必须是真系统 | 评分项 3「系统实现」 | 1:30–3:50 全部用真实录屏，**不得用 AI 生成界面** |
| 3 | 模拟数据要声明 | 提案 §12「identifying simulated and incomplete parts」 | 片中和片尾各出现一次声明 |
| 4 | 不得虚构数字/资质 | 学术诚信 | AI 画面里**不出现任何可读文字、数字、Logo**；文字一律后期叠加 |
| 5 | 音乐/素材授权 | 课程与版权 | 用 royalty-free 音乐，保留授权截图 |

**结论**：AI 只负责约 **45–60 秒**的氛围空镜（开场、痛点、过渡、收尾），占全片不到 20%。剩下的是真人出镜、真机录屏、文字版式。这样既省时间，又不会被判成"拿 AI 糊了一个不存在的系统"。

---

## 1. 交付参数

| 项 | 值 |
|---|---|
| 成片时长 | 5:00（严格 ≤5:30，超出会被扣"未按要求"） |
| 画幅/分辨率 | 16:9 · 1920×1080（4K 可选，交付 1080p 足够） |
| 帧率 | 24 或 25 fps，全片统一 |
| 语言 | 英文口播 + 中英双语字幕（`docs/DAILY_PLAN.md` 已排） |
| 音频 | 旁白 -16 LUFS 左右，音乐 -26 LUFS 垫底，无爆音 |
| 容器 | `.mp4`（H.264 + AAC） |
| AI 空镜总量 | 8 条 × 5–7 秒，共约 50 秒 |

---

## 2. 统一风格锚（每条 prompt 前都要带）

> Photorealistic cinematic documentary, shot on 35mm film, shallow depth of field, natural motion blur, subtle grain, cool teal shadows with warm amber practicals, humid tropical Singapore atmosphere, realistic materials and skin, muted colour grade, no stylisation.

**中文版**：写实电影纪录片质感，35mm 胶片，浅景深，自然运动模糊，轻微颗粒，冷青阴影配暖琥珀实用光，新加坡湿热氛围，材质与肤质真实，低饱和调色，无风格化。

固定这一句的作用：8 条素材来自不同次生成，靠它把色调、质感、镜头语言拉齐，剪辑时不用逐条调色。

---

## 3. 统一负面提示词（每条都追加）

> no text, no captions, no logos, no brand names, no watermark, no UI, no screens, no readable labels, no numbers, no distorted hands, no extra fingers, no warped faces, no flicker, no cartoon, no oversaturation, no slow motion, no shaky camera, no lens flare overdose

**中文版**：无文字、无字幕、无 Logo、无品牌名、无水印、无界面、无屏幕、无可读标签、无数字、手指不变形、人脸不扭曲、无闪烁、非卡通、不过饱和、非慢动作、镜头不抖、无过量光斑。

---

## 4. 分镜表

| 镜号 | 时间码 | 段落 | 时长 | 画面 | 用途 |
|---|---|---|---|---|---|
| S1 | 0:00–0:07 | Hook | 7s | 雨夜冷链月台，托盘推进车厢 | 开场抓人 |
| S2 | 0:07–0:13 | Hook | 6s | 温度记录仪特写，绿灯转琥珀 | 埋"异常" |
| S3 | 0:13–0:22 | Pain | 9s | 纸质台账、夹板、荧光灯 | 人工低效 |
| S4 | 0:22–0:30 | Pain | 8s | 疫苗托盘被贴上红色隔离签 | 损失具象化 |
| S5 | 0:30–0:38 | Value | 8s | 运营中心，大屏虚焦，人指向屏幕 | 协同决策 |
| S6 | 0:38–0:45 | Value | 7s | 蓝调时刻新加坡高速，冷链车行进 | 产品登场过场 |
| S7 | 3:45–3:55 | Trust | 10s | 法规活页夹、贴标签、放大镜 | 讲证据/合规 |
| S8 | 4:35–4:50 | Close | 15s | 清晨 CBD 天际线，缓慢上摇 | 收尾留白 |

> 注：S1–S6 集中在片头 45 秒；S7 插在"证据与局限"段；S8 收尾。中间 1:30–3:45 与 3:55–4:35 全是真实录屏和真人出镜，**不要**用 AI 素材填充，否则会稀释"这是我们做的系统"的可信度。

---

## 5. 逐镜提示词

### S1 · 雨夜冷链月台（7s）

**EN**
```
Photorealistic cinematic documentary, 35mm, shallow depth of field, subtle grain, cool teal shadows with warm amber practicals, humid tropical Singapore atmosphere. Night, heavy rain streaking across a refrigerated pharmaceutical loading bay. A worker in a hi-vis vest and blue nitrile gloves slides a pallet of plain white medical cartons into the back of a white refrigerated truck; cold vapour spills from the door frame, wet asphalt reflects sodium lights. Camera: slow push-in from behind the worker, eye level, slight handheld realism. Faces turned away, hands in focus. 7 seconds, 16:9, 24fps.
```

**中文**
```
写实电影纪录片，35mm，浅景深，轻微颗粒，冷青阴影+暖琥珀实用光，新加坡湿热氛围。夜晚暴雨，药品冷链装卸月台，穿反光背心、戴蓝色丁腈手套的工人把一托盘白色医药纸箱推入白色冷藏车厢，门框涌出冷雾，湿沥青反射钠灯。镜头：从工人身后缓慢推近，平视，轻微手持感。人脸背对镜头，手部清晰。7 秒，16:9，24fps。无文字无 Logo。
```

---

### S2 · 温度记录仪特写（6s）

**EN**
```
Photorealistic cinematic documentary, 35mm macro, very shallow depth of field, cool blue-white clinical light, faint mist. Extreme close-up of a small generic USB temperature data logger lying on stacked vaccine cartons inside a cold room. Its tiny LCD glows soft green, then shifts to amber; frost creeps along the carton edge. Camera: slow rack focus from the logger to the frost, static tripod. No readable numbers on the display. 6 seconds, 16:9, 24fps.
```

**中文**
```
写实电影纪录片，35mm 微距，极浅景深，冷蓝白临床光，薄雾。冷库内，小型通用 USB 温度记录仪放在叠放的疫苗纸箱上，迷你液晶屏先泛柔绿再转琥珀，纸箱边缘结霜。镜头：从记录仪缓慢移焦到霜层，三脚架固定。屏上数字不可读。6 秒，16:9，24fps。
```

---

### S3 · 纸质台账（9s）

**EN**
```
Photorealistic cinematic documentary, 35mm, shallow depth of field, late-afternoon light through venetian blinds, dust motes, muted amber and grey palette. Over-the-shoulder shot of a quality manager at a stainless-steel bench, flipping through printed temperature logs clipped to a board, pen tapping a faded spreadsheet printout, shoulders tense. Camera: slow lateral orbit at desk height. Face out of frame, hands and paper in focus, all print unreadable. 9 seconds, 16:9, 24fps.
```

**中文**
```
写实电影纪录片，35mm，浅景深，午后百叶窗光，浮尘，低饱和琥珀与灰。过肩镜头：质量经理在不锈钢工作台前翻看夹板上的打印温度记录，笔尖敲着褪色的表格打印件，肩背紧绷。镜头：桌面高度缓慢横移环绕。人脸出画，手与纸张清晰，所有印刷内容不可读。9 秒，16:9，24fps。
```

---

### S4 · 红色隔离签（8s）

**EN**
```
Photorealistic cinematic documentary, 35mm, shallow depth of field, sterile clinical white light with a single red accent, high material detail. Top-down slow dolly over rows of glass vaccine vials in a temperature-controlled tray; one tray has been pulled aside and marked with a plain red quarantine tag. A gloved hand enters frame and hesitates above the tray. 8 seconds, 16:9, 24fps, no readable text on the tag.
```

**中文**
```
写实电影纪录片，35mm，浅景深，无菌临床白光+一点红色点缀，材质细节高。俯拍缓慢推进：温控托盘里成排玻璃疫苗瓶，其中一盘被拉到一旁、挂着一张纯红色隔离签。戴手套的手入画，在托盘上方停顿。8 秒，16:9，24fps，签上无可读文字。
```

---

### S5 · 运营中心（8s）

**EN**
```
Photorealistic cinematic documentary, 35mm, shallow depth of field, dusk, warm desk lamps against cool window light, Singapore skyline bokeh outside. Wide shot of a calm logistics operations room: three specialists at desks, one standing and pointing at a large wall display that is completely out of focus with soft glowing abstract shapes. Camera: slow lateral dolly, slightly low angle. Screen content unreadable and abstract, no logos, faces lit from the side and partly turned away. 8 seconds, 16:9, 24fps.
```

**中文**
```
写实电影纪录片，35mm，浅景深，黄昏，暖台灯对冷窗光，窗外新加坡天际线虚焦。宽景：安静的物流运营室，三名专员在工位，一人站起指向墙上一块**完全虚焦**、只有柔和抽象光块的大屏。镜头：缓慢横移，略低角度。屏幕内容不可读且抽象，无 Logo，人脸侧光且部分背对。8 秒，16:9，24fps。
```

> ⚠️ S5 的屏幕必须虚焦。任何"看起来像我们界面"的 AI 画面都会变成伪证。

---

### S6 · 蓝调时刻高速（7s）

**EN**
```
Photorealistic cinematic documentary aerial, 24mm, blue hour, slight atmospheric haze, teal-orange grade. Drone shot following a plain white refrigerated truck along a lit Singapore expressway, light trails from passing traffic, dense green canopy and distant skyline. Camera: slow descending crane move, truck stays centred, subtle parallax. 7 seconds, 16:9, 24fps, no text, no logos.
```

**中文**
```
写实电影纪录片航拍，24mm，蓝调时刻，轻微大气雾，青橙调色。无人机跟拍一辆无标识白色冷藏车行驶在新加坡灯火高速上，过往车流拉出光轨，两侧浓密绿植与远处天际线。镜头：缓慢下降的摇臂运动，卡车保持居中，轻微视差。7 秒，16:9，24fps，无文字无 Logo。
```

---

### S7 · 法规文件（10s）

**EN**
```
Photorealistic cinematic documentary, 50mm, shallow depth of field, warm desk lamp with dramatic side light, dust in the air, dark wood desk. Close-up of thick regulatory binders and printed guidance documents; a hand places a small sticky tab on a paragraph, a magnifier rests beside them. Camera: slow push-in, slight rack focus from the magnifier to the tabbed page. All text out of focus and unreadable. 10 seconds, 16:9, 24fps.
```

**中文**
```
写实电影纪录片，50mm，浅景深，暖台灯戏剧侧光，空气中有浮尘，深色木桌。近景：厚重法规活页夹与打印指南，一只手在某个段落贴上小标签，旁边放着放大镜。镜头：缓慢推近，从放大镜轻微移焦到贴签页。所有文字虚焦不可读。10 秒，16:9，24fps。
```

---

### S8 · 清晨天际线（15s）

**EN**
```
Photorealistic cinematic documentary, 35mm, sunrise, soft golden light, low clouds, gentle grain, hopeful and calm mood. Rooftop view over Singapore's CBD and harbour; camera tilts up slowly from the skyline to the sky, birds crossing frame once. 15 seconds, 16:9, 24fps, no text, no logos.
```

**中文**
```
写实电影纪录片，35mm，日出，柔和金光，低云，轻微颗粒，平静而充满希望。屋顶视角俯瞰新加坡 CBD 与海港；镜头从天际线缓慢上摇到天空，一群鸟掠过画面一次。15 秒，16:9，24fps，无文字无 Logo。
```

---

## 6. 五分钟结构与口播稿

### 时间结构

| 时间 | 段落 | 画面 | 目的 |
|---|---|---|---|
| 0:00–0:30 | Hook + Pain | S1–S4 + 真人出镜 | 让评审在 30 秒内"疼" |
| 0:30–1:05 | Value | S5–S6 + 标题版式 | 一句话说清我们做什么 |
| 1:05–1:30 | 过渡 | 真人出镜 / 手部操作键盘 | 把镜头交给系统 |
| 1:30–3:45 | **Use Case Demo（真实录屏）** | 真机录屏 | 评分项 3 的主战场 |
| 3:45–4:30 | Evidence & Limits | S7 + 数据版式 | 可信度，主动暴露局限 |
| 4:30–5:00 | Close | S8 + 片尾版式 | 收束与声明 |

### 英文口播稿（可直接念，约 340 词 ≈ 2 分 20 秒，余下时间留给画面与操作停顿）

**[0:00–0:30] Hook & Pain**
> At two in the morning, a refrigerated truck leaves a Singapore loading bay. Somewhere inside, a data logger is already recording.
>
> By morning, the log shows a temperature excursion. And three questions land on one quality manager's desk: Is the product still safe? Who signs off? And how do we prove that decision to an auditor six months from now?
>
> Today, those answers live in binders, spreadsheets, and experience. They can take days.

**[0:30–1:05] Value**
> PharmaColdOps compresses that into minutes. It reads the excursion, traces it through an explicit rule path, and recommends one of four dispositions — release, quarantine, retest, or scrap — grounded in WHO, EU GDP and ICH principles.
>
> Every recommendation carries its evidence. And when the evidence isn't there, it says so.

**[1:05–1:30] Transition**
> Here is how it works on a real case. Everything you are about to see is running live on our own system.

**[1:30–3:45] Demo（边操作边讲，按下面 5 个节拍，不必逐字念）**
1. 「We start with today's delivery batch.」— 生成批次、确认发车。
2. 「An excursion is registered against an order in this batch.」— 登记异常，指出发生地点与收货医院。
3. 「The disposition comes with its rule path and the clause behind it.」— 展开结案面板。
4. 「The system also shows what re-routing costs — before and after.」— 切换地图对比虚线/实线。
5. 「Nothing is reserved until a human accepts. And we can ask why.」— 采用方案；向图谱提问，展示引用或"无证据"。

**[3:45–4:30] Evidence & Limits**
> Everything you have seen runs on simulated data. The rule thresholds are engineering assumptions, not clinical validation.
>
> On 57 historical cases, our engine agrees with the human gold standard 54 times — and we report the three it misses.
>
> That honesty is the point. A decision-support tool is only useful if you can see where it stops.

**[4:30–5:00] Close**
> Cold-chain decisions should not depend on who happens to be on shift.
>
> PharmaColdOps — explainable, auditable, and built for the cases that actually go wrong.
>
> Project Group 41, NUS-ISS.

> 口播提示：全程用第一人称复数（we / our），不要念成产品广告腔；语速 130–140 wpm，Demo 段落停下来让操作有呼吸。

---

## 7. 剪辑、字幕与包装

1. **文字全部后期加**：标题字、数据、引用条款、免责声明都用剪辑软件（Premiere / DaVinci / 剪映专业版）叠加，不要指望 AI 生成可读文字。
2. **字幕**：中英双语，英文在上、中文在下；字号 ≥ 24px（1080p），描边或半透明底保证在浅色画面上可读。
3. **音乐**：一条 90–110 BPM 的氛围电子/极简钢琴，痛点段压低，Demo 段保持克制（不要盖住操作声），收尾上扬。**保留授权页面截图**。
4. **转场**：只用硬切和 4–6 帧叠化；AI 素材之间用同一 LUT，避免"拼贴感"。
5. **音效**：雨声、冷库风机、键盘、门吸——轻量铺底，音量 -30 dB 左右。
6. **片尾固定版式**（5 秒）：
   - `Prototype · simulated data · not a production or compliance system`
   - `Project Group 41 · NUS-ISS · 2026`

---

## 8. 工具适配速查

| 工具 | 单条时长 | 用法要点 |
|---|---|---|
| Sora 2 | 4–12s | 支持音画同出 → **必须关音频或后期静音**；英文 prompt 直接可用 |
| Veo 3 | 8s | 自带环境音 → 同样静音；prompt 里加 `no dialogue` |
| Kling / 可灵 | 5/10s | 建议先生成首帧静帧再 image-to-video，8 条素材更统一；中文 prompt 可用 |
| Runway Gen-4 | 5/10s | 镜头运动控制强，用 `camera: slow push-in` 这类短语 |
| 即梦 / 海螺 | 5–10s | 中文 prompt 效果好；注意人物手部，必要时改成"手部出画" |

**一致性工作流（推荐）**：先用同一个风格锚生成 8 张静帧 → 挑 8 张构图最好的 → 逐张 image-to-video → 每段只取 5–7 秒。比纯文生视频稳定得多，也省额度。

---

## 9. 事实与措辞清单

**可以说**
- 「explainable decision-support prototype」/「research prototype」
- 「grounded in WHO / EU GDP / ICH principles」
- 「54 of 57 historical cases agree with our human gold standard」
- 「simulated data」「rule thresholds are engineering assumptions」
- 「offline / sandbox mode available」

**不能说（会被追问或判夸大）**
- ❌「certified」「compliant」「FDA/EMA approved」
- ❌「prevents spoilage」「guarantees safety」
- ❌「saves 30% cost」「reduces waste by X%」（没有实测）
- ❌「real-time sensor integration」（未接真实传感器）
- ❌「100% accurate」「zero errors」
- ❌「production-ready」

**必须出现**
- 模拟数据声明（片中 + 片尾）
- 原型定位（prototype）
- 团队与模块信息（Project Group 41 · NUS-ISS）

---

## 10. 与视频 2 的分工

| | 宣传片（本文件） | 系统设计片 |
|---|---|---|
| 重点 | 商业痛点、价值、用例演示 | 架构、技术选型、可审计性 |
| AI 空镜 | 约 50 秒 | 尽量少（≤20 秒） |
| 数字 | 只放 1 个（54/57） | 放实验表、SHAP、GA 对比 |
| 录屏 | 主链路一遍过 | 分层拆解（规则/KG/调度/双模式） |

避免两条片子讲同一套内容——评审是当两个独立材料打分的。
