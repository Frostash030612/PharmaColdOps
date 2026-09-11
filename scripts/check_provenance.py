#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
标注交付件的完整性 / 泄露自检（可复跑）。

`data/processed/PROVENANCE.md` 声称这些入库件「可审计」「可复跑」，但校验逻辑
原先只活在一个**不入库**的工作脚本里。本脚本把那几项检查固化进仓库：
不拿敏感文件就能跑掉大部分；拿到标注包后能跑全部。

检查项
------
离线（不需要标注包）：

  §2    入库件指纹
        15 份入库件的 SHA-256 须与 `PROVENANCE.md` §2 登记值一致。
  §3.1  探测工作台不得含原轮场景号
        4 份 `probes/*工作台_*.html` 源码里出现 `S0xx`，标注者即可认出被重测的
        是哪几条原轮场景。**只查探测工作台**——两份主工作台本就逐条列出 57 个
        场景号，那是设计如此。
  §3.3  `answer_template.csv` 必须全空

需要标注包（`--private-package`，或环境变量 `PHARMACOLDOPS_ANNOTATION_PACKAGE`）：

  §1    原始作答指纹
        7 份逐人作答的 SHA-256 须与 §1 一致。这些文件按项目红线**永不入库**，
        只登记指纹，故只在包内可核。
  §3.2  入库件不得复现任一份作答
        (a) 完整序列复现；(b) 非 CSV 入库件里出现 >= 8 条连续作答。
        (b) 是刻意加严的：只查「整列复现」会漏掉「贴了半段」——而半段足以
        让同一批标注者重测时认出答案。

用法
----
    python scripts/check_provenance.py
    python scripts/check_provenance.py --private-package <标注包目录>
    python scripts/check_provenance.py --selftest

    `--selftest` 先自证校验器**会失败**：喂进人工构造的坏数据，确认每一项都报错。
    一个永远通过的校验器和没有校验器是一回事（PROVENANCE §3 记过这个教训），
    而且它比没有更糟——假警报会让人开始忽略真警报。

退出码：0 = 全部通过；1 = 任一失败。
"""
import argparse
import csv
import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "data" / "processed" / "PROVENANCE.md"

RUN_LEN = 8          # §3.2(b) 连续作答片段的最小长度
ANSWER_COLS = ("disposition", "gold_label")

# 各项检查的最小规模。**这不是形式主义**：正则一旦匹配不上（表格被改写、
# 标题换了措辞），没有这些守卫的校验器会对空集合「全部通过」。
MIN_SCOPE = {
    "ingested": 10,        # §2 至少登记这么多份入库件
    "private": 5,          # §1 至少登记这么多份原始作答
    "probe_html": 3,       # 至少实际检查了这么多份探测工作台
    "scanned": 10,         # §3.2 至少扫了这么多份入库件
    "template_rows": 50,   # answer_template 至少这么多行
}

SECTION_2 = re.compile(r"\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{16})`")
SECTION_1 = re.compile(r"\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*\d+\s*\|\s*`([0-9a-f]{64})`")
SCENARIO_ID = re.compile(r"S0\d\d")


# --------------------------------------------------------------------------- #
# 纯函数：校验逻辑（--selftest 直接喂坏数据给它们）
# --------------------------------------------------------------------------- #

def digests(data: bytes) -> set:
    """文件的三种行尾形态的 SHA-256 全算出来。

    登记值是首次入库时按**工作区原始字节**（CRLF）算的。换一台机器 clone 时
    行尾可能被规范化成 LF，按字节比会全线假警报，而内容其实分毫未动。
    故三种形态任一命中即算通过。
    """
    lf = data.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return {hashlib.sha256(x).hexdigest() for x in (data, lf, crlf)}


def compare_hashes(rows, resolve) -> list:
    """rows = [(名字, 登记值)]；resolve(名字) -> bytes | None。返回失败明细。

    登记值可能是**截断的**前缀（§2 记 16 位，§1 记全 64 位），故按登记值自身的
    长度截取后比对——拿 16 位前缀去比对 64 位全集永远不相等，会让整张表假警报。
    """
    bad = []
    for name, recorded in rows:
        data = resolve(name)
        if data is None:
            bad.append((name, recorded, "缺失"))
            continue
        variants = {h[:len(recorded)] for h in digests(data)}
        if recorded not in variants:
            bad.append((name, recorded, sorted(variants)[0]))
    return bad


def scan_scenario_ids(text: str) -> list:
    return sorted(set(SCENARIO_ID.findall(text)))


def answer_sequence(rows: list, columns=ANSWER_COLS):
    """从一份作答 CSV 里取作答列；没有作答列（如回连表）返回 None。"""
    if not rows:
        return None
    for col in columns:
        if col in rows[0]:
            return [(r.get(col) or "").strip() for r in rows]
    return None


def longest_run(text: str, seq: list) -> int:
    """seq 在 text 里连续出现的最长片段长度（按逗号连接比对）。"""
    n = len(seq)
    for k in range(n, 0, -1):
        for i in range(n - k + 1):
            if ",".join(seq[i:i + k]) in text:
                return k
    return 0


def check_no_full_sequence(text: str, seq: list):
    """返回 True 表示**发现**整列复现（即有问题）。"""
    return bool(seq) and ",".join(seq) in text


def filled_rows(rows: list, key: str = "scenario_id") -> list:
    """answer_template 里非空的行（除主键外任一列有值）。"""
    return [r for r in rows
            if any((v or "").strip() for k, v in r.items() if k != key)]


# --------------------------------------------------------------------------- #
# 读盘
# --------------------------------------------------------------------------- #

def read_bytes(rel):
    p = ROOT / rel
    return p.read_bytes() if p.is_file() else None


def read_text(rel):
    p = ROOT / rel
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="latin-1")


def parse_provenance():
    md = PROVENANCE.read_text(encoding="utf-8")
    s2 = md[md.index("## 2. "):md.index("## 3. ")]
    s1 = md[md.index("## 1. "):md.index("## 2. ")]
    return SECTION_1.findall(s1), SECTION_2.findall(s2)


def probe_workbenches() -> list:
    d = ROOT / "data" / "scenarios" / "annotation" / "probes"
    return sorted(p for p in d.glob("*工作台_*.html")) if d.is_dir() else []


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #

def selftest() -> bool:
    print("[selftest] 用人工构造的坏数据验证每一项校验器都会失败")
    ok = True

    def expect(label, condition):
        nonlocal ok
        print(f"  [{'ok' if condition else 'FAIL'}] {label}")
        ok = ok and condition

    real = b"scenario_id,disposition,note\nS001,release,\n"
    tampered = real.replace(b"release", b"scrap  ")
    expect("指纹比对能发现被改动的文件",
           not (digests(real) & digests(tampered)))
    expect("指纹比对不会冤枉行尾差异",
           bool(digests(real) & digests(real.replace(b"\n", b"\r\n"))))

    expect("场景号扫描能发现 S0xx",
           scan_scenario_ids("<td>S007</td>") == ["S007"])
    expect("场景号扫描不会把无关文本当命中",
           scan_scenario_ids("<td>release</td>") == [])

    seq = ["release", "scrap", "retest", "quarantine", "release", "scrap",
           "retest", "quarantine", "release"]
    expect("整列复现能被发现",
           check_no_full_sequence("x," + ",".join(seq) + ",y", seq))
    expect("8 条连续片段能被发现",
           longest_run("x," + ",".join(seq[:8]) + ",y", seq) >= RUN_LEN)
    expect("7 条片段不算命中",
           longest_run("x," + ",".join(seq[:7]) + ",y", seq) == 7)

    expect("非空模板行能被发现",
           len(filled_rows([{"scenario_id": "S001", "disposition": "release",
                             "note": ""}])) == 1)
    expect("全空模板不误报",
           filled_rows([{"scenario_id": "S001", "disposition": "",
                         "note": "  "}]) == [])

    expect("空集合会被规模守卫拦下",
           not all([0 >= MIN_SCOPE["ingested"], 0 >= MIN_SCOPE["private"]]))
    return ok


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv) -> int:
    ap = argparse.ArgumentParser(
        description="标注交付件完整性与泄露自检（见 PROVENANCE.md 第 1-3 节）")
    ap.add_argument("--private-package", metavar="DIR",
                    default=os.environ.get("PHARMACOLDOPS_ANNOTATION_PACKAGE"),
                    help="标注包目录（含 7 份原始作答）。不给则跳过 §1 与 §3.2。")
    ap.add_argument("--selftest", action="store_true",
                    help="先自证校验器会失败，再跑真实检查")
    ap.add_argument("--run-len", type=int, default=RUN_LEN,
                    help="§3.2(b) 连续片段的最小长度（默认 %d）" % RUN_LEN)
    args = ap.parse_args(argv)

    failures = []

    if args.selftest and not selftest():
        failures.append("selftest：校验器自身不灵敏")
    if args.selftest:
        print()

    private_rows, ingested_rows = parse_provenance()
    print(f"PROVENANCE.md：§1 登记 {len(private_rows)} 份原始作答，"
          f"§2 登记 {len(ingested_rows)} 份入库件")

    # ---- §2 入库件指纹（离线） ----
    if len(ingested_rows) < MIN_SCOPE["ingested"]:
        failures.append(f"§2 只解析出 {len(ingested_rows)} 行，低于守卫值 "
                        f"{MIN_SCOPE['ingested']}——表格格式可能已变，检查未生效")
        print(f"[FAIL] §2 指纹：解析行数不足，跳过（见上）")
    else:
        bad = compare_hashes(ingested_rows, read_bytes)
        for name, rec, got in bad:
            failures.append(f"§2 {name}：登记 {rec}，实际 {got}")
        print(f"[{'ok' if not bad else 'FAIL'}] §2 入库件指纹："
              f"{len(ingested_rows) - len(bad)}/{len(ingested_rows)} 一致"
              + ("" if not bad else f"，不符 {len(bad)} 份"))

    # ---- §3.1 探测工作台不得含原轮场景号（离线） ----
    probes = probe_workbenches()
    if len(probes) < MIN_SCOPE["probe_html"]:
        failures.append(f"§3.1 只找到 {len(probes)} 份探测工作台，低于守卫值 "
                        f"{MIN_SCOPE['probe_html']}")
        print("[FAIL] §3.1 探测工作台：文件数不足，跳过")
    else:
        leaks = []
        for p in probes:
            txt = p.read_text(encoding="utf-8", errors="replace")
            hits = scan_scenario_ids(txt)
            if hits:
                leaks.append((p.name, hits))
        for name, hits in leaks:
            failures.append(f"§3.1 {name} 含原轮场景号 {hits[:5]}")
        print(f"[{'ok' if not leaks else 'FAIL'}] §3.1 探测工作台无原轮场景号："
              f"{len(probes)} 份，命中 {len(leaks)} 份")

    # ---- §3.3 answer_template 必须全空（离线） ----
    tpl = ROOT / "data" / "scenarios" / "annotation" / "answer_template.csv"
    if not tpl.is_file():
        failures.append("§3.3 answer_template.csv 缺失")
        print("[FAIL] §3.3 answer_template：文件缺失")
    else:
        rows = list(csv.DictReader(tpl.open(encoding="utf-8-sig", newline="")))
        filled = filled_rows(rows)
        if len(rows) < MIN_SCOPE["template_rows"]:
            failures.append(f"§3.3 answer_template 只有 {len(rows)} 行，低于守卫值")
        if filled:
            failures.append(f"§3.3 answer_template 有 {len(filled)} 行非空")
        print(f"[{'ok' if not filled else 'FAIL'}] §3.3 answer_template 全空："
              f"{len(rows)} 行，已填 {len(filled)} 行")

    # ---- §1 / §3.2 需要标注包 ----
    if not args.private_package:
        print("[skip] §1 原始作答指纹、§3.2 序列复现检查："
              "未给 --private-package（或环境变量 PHARMACOLDOPS_ANNOTATION_PACKAGE）")
    else:
        pkg = Path(args.private_package)
        if not pkg.is_dir():
            failures.append(f"标注包目录不存在：{pkg}")
            print(f"[FAIL] 标注包目录不存在：{pkg}")
        else:
            if len(private_rows) < MIN_SCOPE["private"]:
                failures.append(f"§1 只解析出 {len(private_rows)} 行，低于守卫值")
                print("[FAIL] §1 原始作答指纹：解析行数不足，跳过")
            else:
                bad = compare_hashes(private_rows,
                                     lambda n: (pkg / n).read_bytes()
                                     if (pkg / n).is_file() else None)
                for name, rec, got in bad:
                    failures.append(f"§1 {name}：登记 {rec[:16]}...，实际 {got}")
                print(f"[{'ok' if not bad else 'FAIL'}] §1 原始作答指纹："
                      f"{len(private_rows) - len(bad)}/{len(private_rows)} 一致"
                      + ("" if not bad else f"，不符 {len(bad)} 份"))

            seqs, skipped = {}, []
            for name, _ in private_rows:
                f = pkg / name
                if not f.is_file():
                    continue
                rows = list(csv.DictReader(f.open(encoding="utf-8-sig", newline="")))
                seq = answer_sequence(rows)
                if seq is None:
                    skipped.append(name)
                else:
                    seqs[name] = seq
            if skipped:
                print(f"       （无作答列、按设计跳过：{'、'.join(skipped)}）")

            if len(seqs) < MIN_SCOPE["private"] - 2:
                failures.append(f"§3.2 只取到 {len(seqs)} 条作答序列，低于守卫值")
                print("[FAIL] §3.2 序列复现：序列数不足，跳过")
            else:
                full_hits, run_hits, scanned, worst = [], [], 0, (0, "", "")
                for name, _ in ingested_rows:
                    txt = read_text(name)
                    if txt is None:
                        continue
                    scanned += 1
                    for who, seq in seqs.items():
                        if check_no_full_sequence(txt, seq):
                            full_hits.append((name, who))
                        # CSV 入库件本就合法持有 gold 列，而 gold 是双方答案的
                        # 合并——两人一致的连续段落必然与两人各自的序列重合。
                        # 故片段检查只施加于非 CSV 的文本件。
                        if not name.lower().endswith(".csv"):
                            k = longest_run(txt, seq)
                            if k > worst[0]:
                                worst = (k, name, who)
                            if k >= args.run_len:
                                run_hits.append((name, who, k))
                for name, who in full_hits:
                    failures.append(f"§3.2 {name} 完整复现了 {who} 的作答序列")
                for name, who, k in run_hits:
                    failures.append(f"§3.2 {name} 含 {who} 的连续 {k} 条作答")
                if scanned < MIN_SCOPE["scanned"]:
                    failures.append(f"§3.2 只扫到 {scanned} 份入库件，低于守卫值")
                print(f"[{'ok' if not full_hits else 'FAIL'}] §3.2(a) 无整列复现："
                      f"扫 {scanned} 份入库件 x {len(seqs)} 条序列，命中 {len(full_hits)}")
                print(f"[{'ok' if not run_hits else 'FAIL'}] §3.2(b) 非 CSV 件无连续 "
                      f">= {args.run_len} 条作答：命中 {len(run_hits)}"
                      f"（实测最长连续 {worst[0]} 条"
                      + (f"，{worst[1]}" if worst[0] else "") + "）")

    print()
    if failures:
        print(f"[FAIL] {len(failures)} 项未通过：")
        for f in failures:
            print(f"       - {f}")
        return 1
    print("[ok] 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
