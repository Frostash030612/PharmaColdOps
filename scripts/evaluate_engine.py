# -*- coding: utf-8 -*-
"""
PharmaColdOps 引擎评估脚本（9/19）

用法
----
    python scripts/evaluate_engine.py --engine <引擎输出.csv> \
        --private-package <标注包目录>
    python scripts/evaluate_engine.py --selftest --private-package <标注包目录>
                                          # 用 rubric 推导当替身引擎，验证脚本链路

    `--private-package` 指向**标注包**（内含 gold_label_B(1).csv / gold_label_C.csv）。
    本脚本要拿 B、C 两份逐条作答做四列对照，而这两份文件按项目红线
    **不入库**，只在标注包内保存（见 data/processed/PROVENANCE.md §1），
    所以必须从仓库外提供。也可改用环境变量 PHARMACOLDOPS_ANNOTATION_PACKAGE。

引擎输出格式（必需）
--------------------
    scenario_id,disposition
    S001,release
    S002,scrap
    ...（57 行）

    - disposition ∈ {release, retest, quarantine, scrap}
    - 列名大小写不敏感，多余列会被忽略
    - 也接受 id / label / result 等常见别名，见 _norm_header()

输出
----
    <outdir>/引擎评估报告.md      评估正文（四列对照 + 归因分解）
    <outdir>/引擎逐条对照.csv     57 条逐条四列对照（Excel 可直接打开）

为什么要四列对照
----------------
只报「引擎 vs 金标准」会把说明书的负债算到引擎头上：

    rubric v1   ：终版 gold 有 18 条不跟随 rubric 字面（见
                  docs/annotation_findings_v1.md §3.2）——其中 15 条是 v1 第 4 条
                  漏掉了「越限即报废」这条已确认政策，责任在说明书。
    rubric v1.1 ：该 15 条随第 4 条改为 scrap 一次性消解，仅余 3 条；而这 3 条
                  **指向 gold 自身**（S034/S035 为场景次序产物、S052 为 0.1 的边界），
                  故 v1.1 之后不宜再把 A 类一律读作「责任在说明书」。

引擎若忠实实现说明书，在上述条目上必然与 gold 不一致——
看似引擎失分，实为规范与人工判读之间的既有分歧。
本脚本把「引擎 vs gold」的总差异拆成三类（§3），使责任可归属。

纪律
----
    - 本脚本不读 data/scenarios/scenarios.csv 的 gold_label 列
    - 本脚本不导入 src/rule_engine/，只消费其输出文件
    - 不修改任何原始交付件（B、C 的文件以只读方式打开）
"""
import argparse
import csv
import io
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))   # <repo>/scripts
ROOT = os.path.dirname(HERE)                        # <repo>
IDS = ["S%03d" % i for i in range(1, 58)]
LABELS = ["release", "retest", "quarantine", "scrap"]
SEV = {"release": 0, "retest": 1, "quarantine": 2, "scrap": 3}

# ---------------------------------------------------------------------------
# rubric v1.1 §3 产品规格表 + §4 判定规则
#
# 这是 docs/annotation_rubric_v1.1.md §4 六条判定链的机械实现，用于把引擎结果
# 与「说明书字面」对照。它**不是引擎**，也**不是真值**——它只回答
# 「如果严格按说明书执行，这条应该是什么」。
#
# 版本沿革：§3 的阈值数字在 v1 → v1.1 之间**逐格未变**；变的是 §4 第 4 条的
# 处置档（quarantine → scrap）。故本函数相对 v1 的唯一行为差异就是第 4 条。
# 终版 gold 由 **v1** 产出（原始作答指纹见 data/processed/PROVENANCE.md §1）；
# v1.1 未触发重标，理由见 docs/annotation_rubric_v1.1.md §6.1。
#
# 效力：已对 rubric §5 全部 7 个官方工作示例验证通过（7/7；其中示例 D 在 v1.1
# 下由 quarantine 变为 scrap，见该文档 §5）。任何一处规则文本改动都必须同步本
# 表与 rubric_ref()，否则 §3 的归因会错。
# ---------------------------------------------------------------------------
PRODUCTS = {
    "vaccine_2_8":    dict(hi=8,   dur_max=30, dur_scrap=60,
                           mkt_max=10,  mkt_scrap=13,  freeze=True,  retest=True),
    "insulin_2_8":    dict(hi=8,   dur_max=30, dur_scrap=60,
                           mkt_max=10,  mkt_scrap=13,  freeze=True,  retest=True),
    "frozen_m20":     dict(hi=-15, dur_max=15, dur_scrap=30,
                           mkt_max=-12, mkt_scrap=-9,  freeze=False, retest=False),
    "mrna_ultracold": dict(hi=-60, dur_max=60, dur_scrap=120,
                           mkt_max=-55, mkt_scrap=-52, freeze=False, retest=False),
}


def rubric_ref(pid, temp, dur, mkt, pack):
    """rubric §4 六条判定链，按优先级命中即停。返回 (处置, 命中条款号)。"""
    p = PRODUCTS[pid]
    if p["freeze"] and temp <= 0:                                   # 1 冻结报废
        return "scrap", 1
    if pack == "compromised" and temp > p["hi"]:                    # 2 包装破损+超上限
        return "scrap", 2
    if dur >= p["dur_scrap"] or mkt >= p["mkt_scrap"]:              # 3 严重超限
        return "scrap", 3
    if dur > p["dur_max"] or mkt > p["mkt_max"]:                    # 4 超过限值（严格大于）
        return "scrap", 4        # v1.1：quarantine → scrap（政策：越限即报废，不设缓冲档）
    if p["retest"] and (dur >= 0.8 * p["dur_max"]
                        or mkt >= p["mkt_max"] - 0.5):              # 5 接近限值
        return "retest", 5
    return "release", 6                                             # 6 其余


# ---------------------------------------------------------------------------
# 读入
# ---------------------------------------------------------------------------
def _norm_header(name):
    """列名归一，容忍常见别名与大小写/空格差异。"""
    k = name.strip().lower().replace(" ", "_").lstrip("﻿")
    id_alias = {"scenario_id", "id", "scene_id", "scenario", "场景", "场景id", "场景编号"}
    lab_alias = {"disposition", "label", "gold_label", "result", "answer",
                 "处置", "结论", "判定"}
    if k in id_alias:
        return "scenario_id"
    if k in lab_alias:
        return "disposition"
    return k


def read_table(path, label_required=True):
    """读 CSV → {scenario_id: 值}，并返回表头。utf-8-sig 兼容 Excel 导出的 BOM。"""
    if not os.path.exists(path):
        sys.exit("!! 文件不存在: %s" % path)
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.reader(fh) if r and r[0].strip()]
    if not rows:
        sys.exit("!! 文件为空: %s" % path)
    header = [_norm_header(h) for h in rows[0]]
    if "scenario_id" not in header:
        sys.exit("!! %s 找不到 scenario_id 列（表头: %s）" % (path, rows[0]))
    if label_required and "disposition" not in header:
        sys.exit("!! %s 找不到 disposition 列（表头: %s）" % (path, rows[0]))
    i_id = header.index("scenario_id")
    i_lab = header.index("disposition") if "disposition" in header else None
    out = {}
    for r in rows[1:]:
        if i_id >= len(r):
            continue
        sid = r[i_id].strip()
        if not sid:
            continue
        out[sid] = r[i_lab].strip() if (i_lab is not None and i_lab < len(r)) else ""
    return out, rows[0]


def read_scenarios(path):
    """读盲标场景输入（几何量 + 包装 + 阶段）。"""
    scen = {}
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.reader(fh) if r and r[0].strip()]
    for r in rows[1:]:
        scen[r[0].strip()] = dict(pid=r[1].strip(), temp=float(r[2]), dur=float(r[3]),
                                  mkt=float(r[4]), pack=r[5].strip(), stage=r[6].strip())
    return scen


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------
def agreement(a, b):
    return sum(1 for i in IDS if a[i] == b[i])


def kappa(a, b, labels=LABELS):
    """Cohen's kappa（多类别）。"""
    n = len(IDS)
    po = agreement(a, b) / n
    ca, cb = Counter(a[i] for i in IDS), Counter(b[i] for i in IDS)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in labels)
    return (po - pe) / (1 - pe) if pe != 1 else float("nan"), po, pe


def confusion(pred, truth, labels=LABELS):
    """混淆矩阵：conf[真实][预测]。"""
    m = {t: Counter() for t in labels}
    for i in IDS:
        if truth[i] in m:
            m[truth[i]][pred[i]] += 1
    return m


def overrun(i, scen):
    """场景是否越限：时长超过允许值，或 MKT 超过上限（严格大于，与 rubric 第 4 条同口径）。"""
    s, p = scen[i], PRODUCTS[scen[i]["pid"]]
    return (s["dur"] > p["dur_max"], s["mkt"] > p["mkt_max"])


def policy_check(scen, tables, policy="overrun_to_scrap"):
    """
    政策一致性检查：验证某条已经确认的判读政策，是否被各来源一致执行。

    单调性检查（check_monotonicity）只验证序关系，测不出「政策阈值没被一致执行」——
    例如同一档位里 A 条判 scrap、B 条判 quarantine，只要几何上 A 不低于 B，
    单调性就放行。本函数补上这一层。

    policy:
        "overrun_to_scrap" —— 时长或 MKT 任一越限即 scrap。
        该政策由 B、C 在 2026-09-11 盲测复述题中各自独立确认：
        越限场景直接报废，中间不设缓冲档。

    返回 (汇总 dict, 逐条例外 list)。
    """
    if policy != "overrun_to_scrap":
        raise ValueError("未知政策: %s" % policy)
    covered = [i for i in IDS if any(overrun(i, scen))]
    res = {}
    for name, tb in tables:
        exc = [i for i in covered if tb[i] != "scrap"]
        res[name] = dict(total=len(covered), ok=len(covered) - len(exc), exceptions=exc)
    return res, covered


def check_monotonicity(scen, tables):
    """
    严重度单调性：同一产品、包装完好、均不触发冻结时，
    三轴（时长 / MKT / 温度）都不劣且至少一轴更优的场景，处置严重度不得更低。

    注意必须包含温度轴，否则 frozen_m20（freeze=False）会产生假阳性。
    """
    def regime_ok(i):
        s = scen[i]
        return s["pack"] == "intact" and not (
            PRODUCTS[s["pid"]]["freeze"] and s["temp"] <= 0)

    out = {}
    for name, tb in tables:
        v = []
        for pid in PRODUCTS:
            grp = [i for i in IDS if scen[i]["pid"] == pid and regime_ok(i)]
            for a in grp:
                for b in grp:
                    if a == b:
                        continue
                    sa, sb = scen[a], scen[b]
                    if (sa["dur"] >= sb["dur"] and sa["mkt"] >= sb["mkt"]
                            and sa["temp"] >= sb["temp"]
                            and (sa["dur"] > sb["dur"] or sa["mkt"] > sb["mkt"]
                                 or sa["temp"] > sb["temp"])
                            and SEV[tb[a]] < SEV[tb[b]]):
                        v.append((b, a))
        out[name] = v
    return out


def prf(pred, truth, labels=LABELS):
    """每类 precision / recall / F1 + support，以及宏平均。"""
    m = confusion(pred, truth, labels)
    out = {}
    for k in labels:
        tp = m[k][k]
        fp = sum(m[t][k] for t in labels if t != k)
        fn = sum(m[k][p] for p in labels if p != k)
        prec = tp / (tp + fp) if tp + fp else float("nan")
        rec = tp / (tp + fn) if tp + fn else float("nan")
        f1 = (2 * prec * rec / (prec + rec)) if (prec == prec and rec == rec
                                                 and prec + rec) else float("nan")
        out[k] = dict(prec=prec, rec=rec, f1=f1, support=sum(m[k].values()))
    ok = [k for k in labels if out[k]["f1"] == out[k]["f1"]]
    out["_macro_f1"] = sum(out[k]["f1"] for k in ok) / len(ok) if ok else float("nan")
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="PharmaColdOps 引擎评估（9/19）")
    ap.add_argument("--engine", help="引擎输出 CSV 路径")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "data", "processed"),
                    help="输出目录（默认 data/processed）")
    ap.add_argument("--selftest", action="store_true",
                    help="用 rubric 推导当替身引擎，验证脚本链路（非真实评估）")
    ap.add_argument("--private-package", metavar="DIR",
                    default=os.environ.get("PHARMACOLDOPS_ANNOTATION_PACKAGE"),
                    help="标注包目录（含 gold_label_B(1).csv / gold_label_C.csv）；"
                         "见 data/processed/PROVENANCE.md §1")
    args = ap.parse_args()

    pkg = args.private_package
    f_input = os.path.join(ROOT, "data", "scenarios", "annotation", "input_v1.csv")
    f_gold = os.path.join(ROOT, "data", "scenarios", "gold_labels.csv")
    f_b = os.path.join(pkg, "gold_label_B(1).csv") if pkg else None
    f_c = os.path.join(pkg, "gold_label_C.csv") if pkg else None

    missing = [n for n, p in [("gold_label_B(1).csv", f_b), ("gold_label_C.csv", f_c)]
               if not p or not os.path.exists(p)]
    if missing:
        sys.exit(
            "!! 缺少 %s。\n"
            "   B、C 的逐条作答含两位标注者的原始判断，按项目红线不入库，\n"
            "   只在标注包内保存（见 data/processed/PROVENANCE.md §1）。\n"
            "   请用 --private-package <标注包目录> 指定，或设环境变量\n"
            "   PHARMACOLDOPS_ANNOTATION_PACKAGE 指向该目录。"
            % "、".join(missing)
        )

    scen = read_scenarios(f_input)
    B, _ = read_table(f_b)
    C, _ = read_table(f_c)
    gold, _ = read_table(f_gold)
    for nm, tb in [("B", B), ("C", C), ("gold", gold)]:
        miss = [i for i in IDS if i not in tb]
        bad = [i for i in IDS if tb.get(i) not in LABELS]
        if miss or bad:
            sys.exit("!! %s 文件不完整: 缺失 %s 非法 %s" % (nm, miss, bad))

    # 说明书字面
    ref, rule_hit = {}, {}
    for i in IDS:
        s = scen[i]
        ref[i], rule_hit[i] = rubric_ref(s["pid"], s["temp"], s["dur"], s["mkt"], s["pack"])

    # 引擎
    if args.selftest:
        eng = dict(ref)
        engine_desc = "（自检模式：以 rubric 推导充当替身引擎，**不是**真实评估）"
        print("[selftest] using rubric derivation as a stand-in engine")
    else:
        if not args.engine:
            ap.error("需要 --engine <引擎输出.csv>，或用 --selftest 验证脚本")
        eng_raw, hdr = read_table(args.engine)
        miss = [i for i in IDS if i not in eng_raw]
        bad = sorted(set(eng_raw.get(i, "") for i in IDS) - set(LABELS))
        if miss:
            sys.exit("!! 引擎输出缺少 %d 条: %s" % (len(miss), ", ".join(miss[:10])))
        if bad:
            sys.exit("!! 引擎输出含非法取值: %s" % bad)
        eng = {i: eng_raw[i] for i in IDS}
        engine_desc = ""

    # ---- 指标 ----
    pairs = [("gold", gold), ("B", B), ("C", C), ("rubric", ref)]
    metrics = {}
    for name, tb in pairs:
        k, po, pe = kappa(eng, tb)
        metrics[name] = dict(agree=agreement(eng, tb), kappa=k, po=po, pe=pe,
                             prf=prf(eng, tb))

    # ---- 与 gold 的差异归因 ----
    # gold 偏离 rubric 的位置，就是「说明书负债」可能兑现的位置。
    gold_off_spec = [i for i in IDS if gold[i] != ref[i]]
    cat = {i: "" for i in IDS}
    for i in IDS:
        if eng[i] == gold[i]:
            cat[i] = "K"                                  # 一致
        elif gold[i] != ref[i] and eng[i] == ref[i]:
            cat[i] = "A"                                  # 引擎忠实实现说明书，gold 偏离了说明书
        elif gold[i] == ref[i] and eng[i] != ref[i]:
            cat[i] = "B"                                  # gold 与说明书一致，引擎没做到
        else:
            cat[i] = "C"                                  # 三者互不相同
    bucket = Counter(cat[i] for i in IDS)

    # 引擎错的条目里，它是否恰好站到了某个人类一侧
    human_side = Counter()
    for i in IDS:
        if eng[i] == gold[i]:
            continue
        if eng[i] == B[i] == C[i]:
            human_side["与 B、C 同时一致（两人共同判读）"] += 1
        elif eng[i] == B[i]:
            human_side["仅与 B 一致"] += 1
        elif eng[i] == C[i]:
            human_side["仅与 C 一致"] += 1
        else:
            human_side["与任何人类都不同"] += 1

    # 引擎偏离 gold 时的严重度方向
    direc = Counter()
    for i in IDS:
        if eng[i] == gold[i]:
            continue
        d = SEV[eng[i]] - SEV[gold[i]]
        direc["引擎更严" if d > 0 else ("引擎更宽" if d < 0 else "同严重度（不同类）")] += 1

    # ---- 输出：逐条对照 CSV ----
    outdir = args.outdir
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    # 自检产出另起文件名，避免一份「替身引擎」的报告被误当成真实评估结果
    stem = "_SELFTEST_勿采用_" if args.selftest else ""
    f_csv = os.path.join(outdir, stem + "引擎逐条对照.csv")
    with io.open(f_csv, "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["scenario_id", "product", "temp_c", "duration_min", "mkt_c", "packaging",
                     "engine", "gold", "B", "C", "rubric_ref", "rubric_rule_hit",
                     "engine_vs_gold", "error_class"])
        for i in IDS:
            s = scen[i]
            wr.writerow([i, s["pid"], s["temp"], s["dur"], s["mkt"], s["pack"],
                         eng[i], gold[i], B[i], C[i], ref[i], rule_hit[i],
                         "=" if eng[i] == gold[i] else "!=", cat[i]])

    # ---- 输出：markdown 报告 ----
    L = []
    w = L.append
    w("# 引擎评估报告（9/19）")
    w("")
    w("> 生成脚本：`evaluate_engine.py`")
    w("> 引擎输出：`%s`　%s" % (args.engine or "（selftest）", engine_desc))
    w("> 对照来源：终版 `gold_labels.csv`、`gold_label_B(1).csv`、`gold_label_C.csv`、")
    w("> 　　　　　以及 `docs/annotation_rubric_v1.1.md` §4 的机械实现（7/7 通过 §5 示例）")
    w("")
    w("**读法提示**：本报告的主表是 §1 的四列对照，不是任何单一准确率。")
    w("单看「引擎 vs gold」会把说明书的负债算到引擎头上，原因见 §3。")
    w("")

    w("---")
    w("")
    w("## 1. 四列对照")
    w("")
    w("| 对照对象 | 一致 | 一致率 | Cohen's kappa | 宏观 F1 |")
    w("|---|---|---|---|---|")
    for name, label in [("gold", "终版 gold"), ("B", "B 的原始标注"),
                        ("C", "C 的原始标注"), ("rubric", "rubric 推导（说明书字面）")]:
        m = metrics[name]
        w("| %s | %d/57 | %.1f%% | %.4f | %.3f |"
          % (label, m["agree"], m["agree"] / 57 * 100, m["kappa"], m["prf"]["_macro_f1"]))
    w("")
    w("各列的 kappa 与《标注诊断报告》里 B↔C 的 0.6434 可直接比较。")
    w("")
    w("### 1.1 每类 P / R / F1（对照 gold）")
    w("")
    w("| 类别 | precision | recall | F1 | gold 中条数 |")
    w("|---|---|---|---|---|")
    for k in LABELS:
        p = metrics["gold"]["prf"][k]
        w("| `%s` | %.3f | %.3f | %.3f | %d |"
          % (k, p["prec"], p["rec"], p["f1"], p["support"]))
    w("")
    w("> `scrap` 类若 recall 高而 `quarantine` 类 recall 低，通常说明引擎把边界档")
    w("> 一律推到了更重的一侧——结合 §4 的方向统计一起看。")
    w("")

    w("---")
    w("")
    w("## 2. 混淆矩阵（引擎 × gold）")
    w("")
    w("行 = gold，列 = 引擎。对角线为一致。")
    w("")
    w("| gold \\ 引擎 | " + " | ".join("`%s`" % k for k in LABELS) + " | 合计 |")
    w("|---|" + "---|" * (len(LABELS) + 1))
    cm = confusion(eng, gold)
    for t in LABELS:
        row = [cm[t][p] for p in LABELS]
        w("| `%s` | %s | %d |" % (t, " | ".join(str(x) for x in row), sum(row)))
    w("")

    w("---")
    w("")
    w("## 3. 「引擎 vs gold」差异的归因分解 ⭐")
    w("")
    w("终版 gold 有 **%d 条**不跟随 rubric 字面（见《标注诊断报告》§8.1）。" % len(gold_off_spec))
    w("因此「引擎 vs gold」的总差异**不等于**引擎的错误数。按责任归属拆成三类：")
    w("")
    w("| 类 | 含义 | 条数 | 责任方 |")
    w("|---|---|---|---|")
    w("| **K** | 引擎与 gold 一致 | %d | — |" % bucket.get("K", 0))
    w("| **A** | 引擎 == rubric，gold ≠ rubric | %d | **规范分歧**，非引擎错误 |" % bucket.get("A", 0))
    w("| **B** | 引擎 ≠ rubric，gold == rubric | %d | **引擎失误**，需修引擎 |" % bucket.get("B", 0))
    w("| **C** | 三者互不相同 | %d | 需人工复核 |" % bucket.get("C", 0))
    w("")
    n_diff = 57 - bucket.get("K", 0)
    w("引擎与 gold 不一致共 **%d 条**，其中：" % n_diff)
    w("")
    n_a, n_b, n_c = bucket.get("A", 0), bucket.get("B", 0), bucket.get("C", 0)
    if n_a:
        w("- **%d 条（占差异的 %.0f%%）属于 A 类**——引擎忠实实现了说明书，"
          "是 gold 在那些条目上有意越过了说明书。"
          % (n_a, n_a / n_diff * 100 if n_diff else 0))
        w("  **这部分不计入引擎质量**，它是规范与人工判读之间的既有分歧在引擎上的投影。")
    else:
        w("- **0 条属于 A 类**——引擎在 gold 偏离说明书的那些条目上也没有照搬说明书，")
        w("  说明它不是单纯的规格执行器。")
    w("- **%d 条属于 B 类**——gold 与说明书一致，引擎没做到，这部分才是引擎的真实差距。" % n_b)
    w("- **%d 条属于 C 类**——三者互不相同，需要逐条看，见 `引擎逐条对照.csv`。" % n_c)
    w("")
    if n_diff:
        agree_pct = metrics["gold"]["agree"] / 57 * 100
        miss_pct = (n_b + n_c) / 57 * 100
        debt_pct = n_a / 57 * 100
        w("**引擎的真实失误率**（B 类 + C 类，分母 57）：")
        w("`(%d + %d) / 57 = %.1f%%`" % (n_b, n_c, miss_pct))
        w("")
        w("三项相加正好 100%，这是「引擎 vs gold」的完整分解：")
        w("")
        w("| 成分 | 占 57 条 |")
        w("|---|---|")
        w("| 引擎与 gold 一致 | %.1f%% |" % agree_pct)
        w("| 引擎真实失误（B + C） | %.1f%% |" % miss_pct)
        w("| 规范负债投影（A，gold 与说明书分歧） | %.1f%% |" % debt_pct)
        w("| **合计** | **%.1f%%** |" % (agree_pct + miss_pct + debt_pct))
        w("")
        w("**报告「引擎 vs gold %.1f%%」时必须同时给出后两行**，" % agree_pct)
        w("否则看起来像引擎丢了 %.1f 个百分点，实际其中 %.1f 个百分点不是它的问题。"
          % (100 - agree_pct, debt_pct))
    w("")

    w("---")
    w("")
    w("## 4. 引擎偏离 gold 时的方向与立场")
    w("")
    w("### 4.1 严重度方向")
    w("")
    w("| 方向 | 条数 |")
    w("|---|---|")
    for k in ["引擎更严", "引擎更宽", "同严重度（不同类）"]:
        if direc.get(k):
            w("| %s | %d |" % (k, direc[k]))
    w("")
    if direc.get("引擎更严", 0) and not direc.get("引擎更宽", 0):
        w("**引擎在所有分歧上都比 gold 更严，没有一条更宽。**")
        w("方向单侧说明这不是随机误差，而是阈值设得偏保守——")
        w("与 B（6 处倒挂）相比，引擎是另一个方向的单侧：稳定但可能过度报废。")
    elif direc.get("引擎更宽", 0) and not direc.get("引擎更严", 0):
        w("**引擎在所有分歧上都比 gold 更宽，没有一条更严。**")
        w("在药品冷链场景下这是需要优先解释的方向。")
    else:
        w("分歧方向双向分布，未呈现单一偏置。")
    w("")
    w("### 4.2 引擎偏离 gold 时，它站在谁那一边")
    w("")
    w("| 立场 | 条数 |")
    w("|---|---|")
    for k, v in human_side.most_common():
        w("| %s | %d |" % (k, v))
    w("")
    w("「与 B、C 同时一致」的条目值得单独看——那说明引擎与两名人类标注者")
    w("读出了同一件事，而 gold 的仲裁结论与之相反。这类条目是 v1.1 的最强候选证据。")
    w("")

    w("---")
    w("")
    w("## 5. 争议档位专项")
    w("")
    w("《标注诊断报告》§5 记录了 B、C 两人判读一致、却与 rubric 字面不同的那些条目（统称争议档）。")
    w("⚠️ **条数取决于 rubric 版本**：v1 下为 13 条；v1.1 修好第 4 条后只剩 3 条"
      "（S034/S035/S052，均为 gold 侧待复核）。下表按**当前** rubric v1.1 复算。")
    w("引擎在这个档位上的表现最容易暴露它是「照搬说明书」还是「学到了人工判读」：")
    w("")
    disp = [i for i in IDS if B[i] == C[i] != ref[i]]
    w("| 子项 | 条数 |")
    w("|---|---|")
    w("| 争议档总条数 | %d |" % len(disp))
    w("| 其中引擎 == gold（学到了人工判读） | %d |" % sum(1 for i in disp if eng[i] == gold[i]))
    w("| 其中引擎 == rubric（照搬说明书） | %d |" % sum(1 for i in disp if eng[i] == ref[i] != gold[i]))
    w("| 其中引擎两者都不是 | %d |"
      % sum(1 for i in disp if eng[i] != gold[i] and eng[i] != ref[i]))
    w("")
    w("> 引擎 == rubric **不算错**。说明书是它的规格来源，照规格执行是正确行为。")
    w("> 这一栏的意义是：它量化了「规范与人工判读的分歧」有多少会体现在引擎上，")
    w("> 供 v1.1 决定是否需要让引擎跟随人工判读。")
    w("")

    w("---")
    w("")
    w("## 6. 政策一致性检查")
    w("")
    w("单调性检查只验证**序关系**，测不出「同一条政策没被一致执行」：")
    w("同一档位里 A 条判 `scrap`、B 条判 `quarantine`，只要几何上 A 不低于 B，")
    w("单调性就放行。本节补上这一层。")
    w("")
    w("**已确认的政策**：`时长或 MKT 任一越限 → scrap`（不设中间档）。")
    w("依据：B、C 在 2026-09-11 盲测复述题中各自独立确认该档直接报废。")
    w("")
    tables_lookup = {"gold": gold, "B": B, "C": C, "rubric": ref, "engine": eng}
    pol, covered = policy_check(scen, list(tables_lookup.items()))
    w("越限条目共 **%d 条**。" % len(covered))
    w("")
    w("| 来源 | 判 scrap | 例外 |")
    w("|---|---|---|")
    for name, label in [("gold", "终版 gold"), ("engine", "引擎"),
                        ("B", "B 的原始标注"), ("C", "C 的原始标注"),
                        ("rubric", "rubric 推导")]:
        r = pol[name]
        ex = ("、".join("%s(%s)" % (i, tables_lookup[name][i])
                        for i in r["exceptions"]) if r["exceptions"] else "—")
        w("| %s | %d/%d | %s |" % (label, r["ok"], r["total"], ex))
    w("")
    w("> **rubric v1.1 已把该政策写进第 4 条**（`quarantine` → `scrap`），故 `rubric` 一栏")
    w("> 在本版下**不再有例外**。v1 下这一栏有 15 条例外、全部落在第 4 条档位——")
    w("> 那不是执行错误，而是 v1 文本漏掉了这条已确认政策，v1.1 已补上。")
    w("> 决策记录见 `docs/annotation_rubric_v1.1.md` §0.1–§0.2。")
    w("")

    w("### 6.1 单调性检查（三轴）")
    w("")
    mono = check_monotonicity(scen, [("gold", gold), ("engine", eng),
                                     ("B", B), ("C", C), ("rubric", ref)])
    w("| 来源 | 违反单调性 |")
    w("|---|---|")
    for name, label in [("gold", "终版 gold"), ("engine", "引擎"),
                        ("B", "B 的原始标注"), ("C", "C 的原始标注"),
                        ("rubric", "rubric 推导")]:
        w("| %s | %d 处 |" % (label, len(mono[name])))
    w("")
    w("> 检查必须包含 `excursion_temp_c` 轴，否则 `frozen_m20`（`freeze=False`）会产生假阳性。")
    w("")

    w("---")
    w("")
    w("## 7. 逐条差异清单")
    w("")
    diffs = [i for i in IDS if eng[i] != gold[i]]
    if not diffs:
        w("引擎与 gold 完全一致（57/57）。")
    else:
        w("共 %d 条，按归因类别排序：" % len(diffs))
        w("")
        w("| 场景 | 产品 | 温度 | 时长 | MKT | 引擎 | gold | B | C | rubric | 类 |")
        w("|---|---|---|---|---|---|---|---|---|---|---|")
        for i in sorted(diffs, key=lambda x: (cat[x], x)):
            s = scen[i]
            w("| %s | `%s` | %+.1f | %.0f | %+.1f | `%s` | `%s` | `%s` | `%s` | `%s` | **%s** |"
              % (i, s["pid"], s["temp"], s["dur"], s["mkt"],
                 eng[i], gold[i], B[i], C[i], ref[i], cat[i]))
        w("")
        w("类 K 不出现在上表（一致）。A/B/C 的含义见 §3。")
    w("")

    w("---")
    w("")
    w("*本报告由 `evaluate_engine.py` 生成。*")
    w("*`data/scenarios/scenarios.csv` 的 `gold_label` 列全程未被读取。*")
    w("*原始交付件 `gold_label_B(1).csv`、`gold_label_C.csv` 只读打开，未被修改。*")

    f_md = os.path.join(outdir, stem + "引擎评估报告.md")
    with io.open(f_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))

    # ---- 控制台摘要（ASCII，避免 Windows GBK 控制台报错）----
    print("=" * 62)
    print("engine vs ...     agree   rate    kappa   macroF1")
    print("-" * 62)
    for name, label in [("gold", "gold"), ("B", "B"), ("C", "C"), ("rubric", "rubric")]:
        m = metrics[name]
        print("%-16s  %2d/57  %5.1f%%  %6.4f  %6.3f"
              % (label, m["agree"], m["agree"] / 57 * 100, m["kappa"], m["prf"]["_macro_f1"]))
    print("-" * 62)
    print("diff vs gold: %d  (K=%d A=%d B=%d C=%d)"
          % (n_diff, bucket.get("K", 0), bucket.get("A", 0),
             bucket.get("B", 0), bucket.get("C", 0)))
    print("  A = spec-debt (engine followed rubric, gold did not) -- NOT an engine fault")
    print("  B = genuine engine miss")
    print("  C = three-way disagreement")
    print()
    print("written: %s" % f_md)
    print("written: %s" % f_csv)


if __name__ == "__main__":
    main()
