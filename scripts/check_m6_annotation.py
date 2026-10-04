"""M6 评审端「提交前自检」：只查格式与完整性，不判断题目内容。

评审（或协调人）在自己填完 CSV 后先跑一次，避免交给协调人后才发现空标签、
缺行、非法取值、指纹被编辑器改坏等问题。判据与
`scripts/evaluate_m6_independent.py` 的 `read_annotations` 对齐，报错关键词照抄，
因此这里的「错误」就是协调人跑 `score` 时会拒绝的原因。

用法（仓库根目录；Windows 用 .venv\\Scripts\\python.exe）：

    # 第一阶段：意图标签
    .venv\\Scripts\\python.exe scripts\\check_m6_annotation.py ^
      --questions data\\processed\\m6-blind-20261003-v3\\blind-intent\\questions.csv ^
      --intent    data\\processed\\m6-blind-20261003-v3\\blind-intent\\intent-A.csv

    # 第二阶段：答案／证据评分
    .venv\\Scripts\\python.exe scripts\\check_m6_annotation.py ^
      --responses data\\processed\\m6-blind-20261003-v3\\answer-review\\responses.json ^
      --ratings   data\\processed\\m6-blind-20261003-v3\\answer-review\\ratings-A.csv

    # 两阶段都填完后顺便核对「同一评审 ID」（phase reviewer identities must agree）
    .venv\\Scripts\\python.exe scripts\\check_m6_annotation.py ^
      --intent intent-A.csv --ratings ratings-A.csv

本工具只读入你手上的材料：不使用 predictions.private.json、不联网、不写任何文件、
不替你做任何判断。它不能代替协调人的官方 `score`，也不验证来源 URL 内容、
不验证评审是否真是两个人。
"""
import argparse
import ast
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORER = ROOT / 'scripts' / 'evaluate_m6_independent.py'

# 与 evaluate_m6_independent.py 同源的枚举；下面 check_scorer_constants() 会核对是否漂移。
INTENTS = ['why_disposition', 'audit_chain', 'product_requirements', 'cause_context',
           'disposition_stats', 'unsupported']
RATINGS = ['answer_correctness', 'evidence_relevance', 'evidence_sufficiency',
           'refusal_appropriate', 'unsupported_claims']

INTENT_COLUMNS = ['question_id', 'question', 'lang', 'packet_sha256', 'annotator_id',
                  'expected_intent', 'acceptable_intents', 'note']
RATING_COLUMNS = ['question_id', 'packet_sha256', 'response_sha256', 'annotator_id',
                  *RATINGS, 'relevant_evidence_ids', 'checked_source_urls', 'note']

HEX64 = re.compile(r'^[0-9a-f]{64}$')
URLISH = re.compile(r'^https?://', re.IGNORECASE)


def allowed_for(key):
    """与评分脚本 read_annotations 的 allowed 集合逐字对齐。"""
    if key == 'refusal_appropriate':
        return {'0', '1', 'NA'}
    if key == 'unsupported_claims':
        return {'0', '1'}
    if key in ('evidence_relevance', 'evidence_sufficiency'):
        return {'0', '1', '2', 'NA'}
    return {'0', '1', '2'}


class Report:
    def __init__(self, label):
        self.label = label
        self.errors = []
        self.warnings = []
        self.notes = []
        self.rows = 0

    def error(self, where, message, scorer_says=None):
        tail = f"（score 会报：{scorer_says}）" if scorer_says else ''
        self.errors.append(f"{where} {message}{tail}")

    def warn(self, where, message):
        self.warnings.append(f"{where} {message}")

    def note(self, message):
        self.notes.append(message)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def hash_problem(value):
    text = (value or '').strip()
    if not text:
        return '空'
    if not HEX64.match(text):
        return f'格式可疑（{text[:24]}{"…" if len(text) > 24 else ""}）——长哈希可能被 Excel 改写'
    return None


def check_scorer_constants(report):
    if not SCORER.exists():
        report.warn('环境', f'找不到 {SCORER.relative_to(ROOT)}，跳过枚举漂移核对')
        return
    found = {}
    for node in ast.parse(SCORER.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ('INTENTS', 'RATINGS'):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pass
    if not found:
        report.warn('环境', '无法从评分脚本解析 INTENTS／RATINGS，跳过漂移核对')
        return
    if found.get('INTENTS') != INTENTS:
        report.warn('环境', f'INTENTS 与评分脚本不一致：脚本为 {found.get("INTENTS")}')
    if found.get('RATINGS') != RATINGS:
        report.warn('环境', f'RATINGS 与评分脚本不一致：脚本为 {found.get("RATINGS")}')


def check_columns(report, fields, expected):
    missing = [c for c in expected if c not in fields]
    if missing:
        report.error('表头', f'缺少列 {missing}', 'KeyError／列取空值')
    extra = [c for c in fields if c not in expected]
    if extra:
        report.warn('表头', f'多出列 {extra}（评分脚本按列名取值，多余列会被忽略）')


def check_rows_and_qids(report, rows, qids):
    report.rows = len(rows)
    seen = {}
    for index, row in enumerate(rows, start=2):
        qid = (row.get('question_id') or '').strip()
        where = f'第 {index} 行（{qid or "无 question_id"}）'
        if None in row:
            report.error(where, f'列数多于表头（多出 {len(row[None])} 个字段）——'
                                '常见原因是问句里有未加引号的逗号',
                         '列取值错位／KeyError')
        short = [key for key, value in row.items() if key is not None and value is None]
        if short:
            report.error(where, f'列数少于表头，缺 {short}（引号未闭合或行被截断）',
                         'KeyError／空值')
        if not qid:
            report.error(where, 'question_id 为空', 'unknown or duplicate annotation identity')
            continue
        if qid in seen:
            report.error(where, f'question_id 重复（已在第 {seen[qid]} 行出现）',
                         'unknown or duplicate annotation identity')
            continue
        seen[qid] = index
        if qids is not None and qid not in qids:
            report.error(where, 'question_id 不在本批 questions.csv 里（可能混入别的批次）',
                         'unknown or duplicate annotation identity')
    if qids is not None:
        missing = [q for q in qids if q not in seen]
        if missing:
            preview = '、'.join(missing[:6]) + ('…' if len(missing) > 6 else '')
            report.error('行数', f'少 {len(missing)} 行：{preview}（不许删题、不许只填一部分）',
                         'all packet rows must be annotated; no selective denominator')
        extra = [q for q in seen if q not in qids]
        if extra:
            report.error('行数', f'多出 {len(extra)} 个非本批 question_id',
                         'unknown or duplicate annotation identity')
        if not missing and not extra:
            report.note(f'行数 {len(rows)} 与 questions.csv 的 {len(qids)} 条一致')


def check_identity(report, rows, label):
    ids = {}
    for index, row in enumerate(rows, start=2):
        qid = (row.get('question_id') or '').strip() or '?'
        raw = row.get('annotator_id')
        if raw is None or not raw.strip():
            report.error(f'第 {index} 行（{qid}）', 'annotator_id 为空',
                         'human annotator identity missing')
            continue
        if raw != raw.strip():
            report.warn(f'第 {index} 行（{qid}）', f'annotator_id 前后有空格（"{raw}"）')
        ids.setdefault(raw.strip(), 0)
        ids[raw.strip()] += 1
    if len(ids) > 1:
        report.error('全文', f'annotator_id 不唯一：{sorted(ids)}（一个文件只能是一位评审）',
                     'one consistent reviewer per file required')
    elif ids:
        report.note(f'annotator_id = {next(iter(ids))}（两阶段必须用同一个 ID，且与另一位评审不同）')
    return next(iter(ids)) if len(ids) == 1 else None


def check_packet_sha(report, rows, qids_source):
    values = {(row.get('packet_sha256') or '').strip() for row in rows}
    for index, row in enumerate(rows, start=2):
        qid = (row.get('question_id') or '').strip() or '?'
        problem = hash_problem(row.get('packet_sha256'))
        if problem:
            report.error(f'第 {index} 行（{qid}）', f'packet_sha256 {problem}',
                         'annotation belongs to a different response packet')
    if len(values) > 1:
        report.error('全文', f'packet_sha256 在同一文件内不一致（{len(values)} 种取值）',
                     'annotation belongs to a different response packet')
    if qids_source:
        expected = {sha for sha in qids_source if sha}
        if len(expected) == 1 and values != expected:
            only = next(iter(expected))
            report.error('全文', f'packet_sha256 与 questions.csv 的 {only[:16]}… 不一致',
                         'annotation belongs to a different response packet')
        elif values and values <= expected:
            report.note('packet_sha256 与 questions.csv 一致')


def check_intent(report, rows):
    for index, row in enumerate(rows, start=2):
        qid = (row.get('question_id') or '').strip() or '?'
        where = f'第 {index} 行（{qid}）'
        value = (row.get('expected_intent') or '').strip()
        if row.get('expected_intent') != value:
            report.warn(where, f'expected_intent 前后有空格（"{row.get("expected_intent")}"）')
        acceptable_raw = row.get('acceptable_intents') or ''
        if value not in INTENTS + ['ambiguous']:
            report.error(where, f'expected_intent = "{value}"，不是合法值',
                         'unlabelled or invalid intent; cannot score independence')
        elif value == 'ambiguous':
            if ' ' in acceptable_raw:
                report.warn(where, 'acceptable_intents 含空格（规范是英文分号连接、两侧不加空格）')
            accepted = [p for p in acceptable_raw.split(';') if p]
            illegal = [p for p in accepted if p not in INTENTS]
            if not accepted or illegal:
                report.error(where, f'ambiguous 必须给出可接受集合，且只能是六个任务标签'
                                    f'（当前 "{acceptable_raw}"，非法项 {illegal}）',
                             'ambiguous input requires explicit acceptable intent set')
            if not (row.get('note') or '').strip():
                report.warn(where, 'ambiguous 建议在 note 写清为什么有多种合理解释（指南 §3 要求）')
        else:
            if acceptable_raw.strip():
                report.warn(where, f'非 ambiguous 却填了 acceptable_intents="{acceptable_raw}"：'
                                   '只要另一位没填同样的内容，这一行就会被算作分歧、需要仲裁')
            if not (row.get('note') or '').strip():
                report.warn(where, 'note 为空（建议写判断理由，便于仲裁与复盘）')


def check_ratings(report, rows, responses):
    by_id = {}
    if responses is not None:
        by_id = {item.get('question_id'): item.get('response_sha256') for item in responses}
    for index, row in enumerate(rows, start=2):
        qid = (row.get('question_id') or '').strip() or '?'
        where = f'第 {index} 行（{qid}）'
        for key in RATINGS:
            raw = row.get(key)
            if raw is not None and raw != raw.strip():
                report.warn(where, f'{key} 前后有空格（"{raw}"）')
            if (raw or '') not in allowed_for(key):
                report.error(where, f'{key} = "{raw}"，合法值为 '
                                    f'{sorted(allowed_for(key))}',
                             'incomplete or invalid human quality rating')
        if not (row.get('checked_source_urls') or '').strip():
            report.error(where, 'checked_source_urls 为空（每一行都要有你真的打开过的来源，'
                                '含超范围／无证据的题）',
                         'human source review provenance missing')
        else:
            items = [p for p in re.split(r'[;；]', row['checked_source_urls']) if p.strip()]
            odd = [p.strip() for p in items if not URLISH.match(p.strip())]
            if odd and len(odd) == len(items):
                report.warn(where, f'checked_source_urls 里没有 http(s) 链接（{odd[:2]}）——'
                                   '确认这确实是可核对的来源，而不是"已经检查"之类的话')
        problem = hash_problem(row.get('response_sha256'))
        if problem:
            report.error(where, f'response_sha256 {problem}', 'response content changed')
        elif responses is not None:
            expected = by_id.get(qid)
            if expected is None:
                report.error(where, 'responses.json 里没有这个 question_id',
                             'unknown or duplicate annotation identity')
            elif (row.get('response_sha256') or '').strip() != expected:
                report.error(where, 'response_sha256 与 responses.json 不一致（题目与回答不是同一批）',
                             'response content changed')
        note = (row.get('note') or '').strip()
        if not note:
            hints = []
            if (row.get('unsupported_claims') or '').strip() == '1':
                hints.append('unsupported_claims=1 需说明发现了什么无依据断言（指南 §4）')
            if not (row.get('relevant_evidence_ids') or '').strip():
                hints.append('relevant_evidence_ids 留空需解释')
            tail = f'；另外：{"；".join(hints)}' if hints else ''
            report.warn(where, f'note 为空（建议写扣分理由与来源章节／页码）{tail}')
    if responses is None:
        report.warn('全文', '未提供 responses.json，无法核对 response_sha256 与回答是否同批')
    elif not any('response_sha256' in message for message in report.errors):
        report.note(f'response_sha256 全部与 responses.json 一致（{len(rows)} 条）')


def print_report(reports):
    total_errors = total_warnings = 0
    for report in reports:
        print(f'\n=== {report.label}（{report.rows} 行）===')
        for message in report.notes:
            print(f'  [通过] {message}')
        for message in report.errors:
            print(f'  [错误] {message}')
        for message in report.warnings:
            print(f'  [警告] {message}')
        if not (report.notes or report.errors or report.warnings):
            print('  （没有可检查的内容）')
        total_errors += len(report.errors)
        total_warnings += len(report.warnings)
    print(f'\n=== 汇总：错误 {total_errors} 项，警告 {total_warnings} 项 ===')
    if total_errors:
        print('先改完所有 [错误] 再交给协调人——这些正是 score 会拒绝的原因。'
              '不要靠改 ID、编 URL、抄系统预测或删题来绕过。')
    else:
        print('格式层面没有 [错误]。[警告] 不影响脚本运行，但会影响仲裁成本与报告可读性，建议一并处理。')
    print('自检只覆盖格式：题目意图与回答质量必须由你本人独立判断，'
          '不能用 AI 或系统预测代填（见 docs/M6独立评估.md 红线）。')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--questions', type=Path, help='blind-intent/questions.csv')
    parser.add_argument('--intent', type=Path, help='你自己那一档 intent-A.csv 或 intent-B.csv')
    parser.add_argument('--responses', type=Path, help='answer-review/responses.json')
    parser.add_argument('--ratings', type=Path, help='你自己那一档 ratings-A.csv 或 ratings-B.csv')
    args = parser.parse_args()
    if not args.intent and not args.ratings:
        parser.error('至少提供 --intent 或 --ratings 中的一个')

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    reports = []
    environment = Report('环境')
    check_scorer_constants(environment)
    reports.append(environment)

    qids = None
    qids_source = None
    if args.questions:
        if not args.questions.exists():
            environment.error('文件', f'找不到 {args.questions}', 'FileNotFoundError')
        else:
            _, question_rows = read_csv(args.questions)
            qids = [(row.get('question_id') or '').strip() for row in question_rows]
            qids_source = {(row.get('packet_sha256') or '').strip() for row in question_rows}
            environment.note(f'questions.csv：{len(qids)} 条题')
    else:
        environment.warn('文件', '未提供 --questions，跳过行数／题目覆盖检查')

    identity = {}
    for kind, path in (('intent', args.intent), ('ratings', args.ratings)):
        if not path:
            continue
        label = f'{"意图标签" if kind == "intent" else "答案／证据评分"}：{path.name}'
        report = Report(label)
        reports.append(report)
        if not path.exists():
            report.error('文件', f'找不到 {path}', 'FileNotFoundError')
            continue
        try:
            fields, rows = read_csv(path)
        except UnicodeDecodeError:
            report.error('编码', '不是 UTF-8（Excel 另存为 GBK／ANSI 会出现这种错）——'
                                '请另存为 UTF-8 CSV', 'UnicodeDecodeError')
            continue
        check_columns(report, fields, INTENT_COLUMNS if kind == 'intent' else RATING_COLUMNS)
        check_rows_and_qids(report, rows, qids)
        check_packet_sha(report, rows, qids_source)
        identity[kind] = check_identity(report, rows, label)
        if kind == 'intent':
            check_intent(report, rows)
        else:
            responses = None
            if args.responses:
                if not args.responses.exists():
                    report.error('文件', f'找不到 {args.responses}', 'FileNotFoundError')
                else:
                    try:
                        responses = json.loads(args.responses.read_text(encoding='utf-8'))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        report.error('文件', f'{args.responses} 不是可解析的 JSON', 'JSONDecodeError')
            check_ratings(report, rows, responses)

    if identity.get('intent') and identity.get('ratings'):
        pair = Report('两阶段身份')
        reports.append(pair)
        if identity['intent'] == identity['ratings']:
            pair.note(f'两阶段的 annotator_id 一致：{identity["intent"]}')
        else:
            pair.error('身份', f'第一阶段 {identity["intent"]} 与第二阶段 {identity["ratings"]} 不一致',
                       'phase reviewer identities must agree')

    print_report(reports)
    return 1 if any(report.errors for report in reports) else 0


if __name__ == '__main__':
    raise SystemExit(main())
