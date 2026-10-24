#!/usr/bin/env node
/** m6_review_form.html 的纯逻辑自测。
 *
 * 从页面里取出内联脚本、在 Node 里调用它的纯函数，验证：
 *   1. 真实空白模板「解析 → 导出」逐字节还原（未填列不会被改写）；
 *   2. 空白模板自检必须报错（与官方 score 的拒绝行为一致）；
 *   3. 填满后自检通过，且 question / lang / packet_sha256 / response_sha256 原样保留；
 *   4. ambiguous 的合法值规则、评分字段合法值规则；
 *   5. responses.json 能补齐第二阶段要展示的问句。
 * 只读文件、不写文件、不打开浏览器、不打印任何评审内容（只报检查结果）。
 *
 * 用法：node scripts/m6_review_form_selftest.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const PACK = path.join(root, "data/qa/m6-review-20261003-v3");

const html = fs.readFileSync(path.join(here, "m6_review_form.html"), "utf8");
const blocks = html.match(/<script>[\s\S]*?<\/script>/g) || [];
if (blocks.length !== 1) {
  console.error("FAIL: 期望页面里恰好 1 个内联 <script>，实际 " + blocks.length);
  process.exit(1);
}
(0, eval)(blocks[0].replace(/^<script>/, "").replace(/<\/script>$/, ""));
const F = globalThis.M6Form;
if (!F) {
  console.error("FAIL: 页面没有导出 M6Form");
  process.exit(1);
}

const results = [];
const check = (name, fn) => {
  try { results.push(["OK", name, fn() || ""]); }
  catch (error) { results.push(["FAIL", name, error.message]); }
};
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const read = relative => fs.readFileSync(path.join(PACK, relative), "utf8");
const rowsOf = relative => F.parseCSV(read(relative));

for (const [mode, relative] of [["intent", "blind-intent/intent-A.csv"],
                                ["ratings", "answer-review/ratings-A.csv"]]) {
  check(mode + " 空白模板往返逐字节一致（" + relative + "）", () => {
    const text = read(relative);
    const rows = F.parseCSV(text);
    const eol = F.detectEol(text);
    const items = F.itemsFromCSV(rows, mode);
    const out = F.buildExport(rows[0], items, mode, "");
    const again = F.toCSV(out.header, out.rows, eol, text.endsWith(eol));
    assert(rows.length - 1 === 53, "数据行数为 " + (rows.length - 1) + "，期望 53");
    assert(again === text, "导出与原文不一致（" + again.length + " vs " + text.length + " 字节）");
    return (rows.length - 1) + " 行 × " + rows[0].length + " 列";
  });
}

check("CSV 含逗号／引号／换行时往返正确", () => {
  const source = 'a,b\n"x,1","say ""hi"""\n"multi\nline",z\n';
  const rows = F.parseCSV(source);
  assert(rows.length === 3, "行数 " + rows.length);
  assert(rows[1][0] === "x,1" && rows[1][1] === 'say "hi"', "引号解析错误");
  assert(rows[2][0] === "multi\nline", "字段内换行解析错误");
  const again = F.toCSV(rows[0], rows.slice(1).map(r => ({ a: r[0], b: r[1] })), "\n", true);
  assert(F.parseCSV(again)[2][0] === "multi\nline", "重新序列化后丢失字段内换行");
  return "逗号／双引号／换行均通过";
});

check("空白意图模板自检必须报错", () => {
  const rows = rowsOf("blind-intent/intent-A.csv");
  const items = F.itemsFromCSV(rows, "intent");
  const report = F.validate(rows[0], items, "intent", "");
  assert(report.errors.filter(t => t.indexOf("expected_intent") >= 0).length === 53,
         "expected_intent 错误数不是 53");
  assert(report.errors.some(t => t.indexOf("annotator_id") >= 0), "annotator_id 为空没报错");
  assert(F.validate(rows[0], items, "intent", "reviewer_A").errors.length === 53,
         "给了 annotator_id 后应当只剩 53 项错误");
  return report.errors.length + " 项错误（含 53 条未填标签）";
});

check("空白评分模板自检必须报错", () => {
  const rows = rowsOf("answer-review/ratings-A.csv");
  const items = F.itemsFromCSV(rows, "ratings");
  const report = F.validate(rows[0], items, "ratings", "reviewer_A");
  assert(report.errors.filter(t => t.indexOf("incomplete") >= 0).length === 53 * 5,
         "评分字段错误数不是 53×5");
  assert(report.errors.filter(t => t.indexOf("checked_source_urls") >= 0).length === 53,
         "checked_source_urls 错误数不是 53");
  return report.errors.length + " 项错误（53×5 评分 + 53 来源）";
});

check("填满 53 条意图后自检通过，且问句与指纹原样保留", () => {
  const text = read("blind-intent/intent-A.csv");
  const rows = F.parseCSV(text);
  const items = F.itemsFromCSV(rows, "intent");
  items.forEach((item, index) => {
    const value = F.INTENT_VALUES[index % F.INTENT_VALUES.length];
    item.answer.expected_intent = value;
    item.answer.acceptable_intents = value === "ambiguous" ? ["why_disposition", "audit_chain"] : [];
    item.answer.note = "selftest 占位理由";
  });
  const report = F.validate(rows[0], items, "intent", "reviewer_A");
  assert(report.errors.length === 0, "仍有错误：" + report.errors.slice(0, 3).join(" ｜ "));

  const out = F.buildExport(rows[0], items, "intent", "reviewer_A");
  const back = F.parseCSV(F.toCSV(out.header, out.rows, "\n", true));
  assert(back.length - 1 === 53, "导出后行数 " + (back.length - 1));
  const before = {}, after = {};
  F.itemsFromCSV(rows, "intent").forEach(item => { before[item.qid] = item.raw; });
  F.itemsFromCSV(back, "intent").forEach(item => { after[item.qid] = item.raw; });
  for (const qid of Object.keys(before)) {
    for (const key of ["question", "lang", "packet_sha256"]) {
      assert(before[qid][key] === after[qid][key], qid + " 的 " + key + " 被改动");
    }
    assert(after[qid].annotator_id === "reviewer_A", qid + " 的 annotator_id 没写进去");
    assert(after[qid].note === "selftest 占位理由", qid + " 的 note 没写进去");
    assert(after[qid].expected_intent === items.find(i => i.qid === qid).answer.expected_intent,
           qid + " 的 expected_intent 没写进去");
  }
  return "53 行写入且 3 列指纹未变";
});

check("ambiguous 必须有可接受集合，非 ambiguous 不该有", () => {
  const rows = rowsOf("blind-intent/intent-A.csv");
  const items = F.itemsFromCSV(rows, "intent");
  items.forEach(item => { item.answer.expected_intent = "why_disposition"; item.answer.note = "x"; });
  items[0].answer.expected_intent = "ambiguous";
  items[0].answer.acceptable_intents = [];
  const missing = F.validate(rows[0], items, "intent", "reviewer_A");
  assert(missing.errors.some(t => t.indexOf("ambiguous") >= 0), "缺 acceptable_intents 却没报错");

  items[0].answer.acceptable_intents = ["why_disposition", "not_a_label"];
  const illegal = F.validate(rows[0], items, "intent", "reviewer_A");
  assert(illegal.errors.some(t => t.indexOf("not_a_label") >= 0), "非法可接受标签没报错");

  items[0].answer.expected_intent = "why_disposition";
  items[0].answer.acceptable_intents = ["audit_chain"];
  const soft = F.validate(rows[0], items, "intent", "reviewer_A");
  assert(soft.errors.length === 0, "非 ambiguous 填了可接受集合不该报错：" + soft.errors[0]);
  assert(soft.warnings.some(t => t.indexOf("分歧") >= 0), "应给出会被算作分歧的提醒");
  return "缺集合报错、非法项报错、多余集合仅提醒";
});

check("评分字段合法值与 checked_source_urls 必填", () => {
  const rows = rowsOf("answer-review/ratings-A.csv");
  const items = F.itemsFromCSV(rows, "ratings");
  items.forEach(item => {
    item.ratings.answer_correctness = "NA";
    item.ratings.evidence_relevance = "1.5";
    item.ratings.evidence_sufficiency = "2";
    item.ratings.refusal_appropriate = "NA";
    item.ratings.unsupported_claims = "0";
    item.ratings.checked_source_urls = "";
  });
  const bad = F.validate(rows[0], items, "ratings", "reviewer_A");
  assert(bad.errors.length >= 53 * 3, "非法评分未被拦住，只报了 " + bad.errors.length);
  items.forEach(item => {
    item.ratings.answer_correctness = "2";
    item.ratings.evidence_relevance = "NA";
    item.ratings.checked_source_urls = "https://example.org/source";
  });
  const good = F.validate(rows[0], items, "ratings", "reviewer_A");
  assert(good.errors.length === 0, "填好后仍有错误：" + good.errors.slice(0, 2).join(" ｜ "));
  const out = F.buildExport(rows[0], items, "ratings", "reviewer_A");
  const back = F.parseCSV(F.toCSV(out.header, out.rows, "\n", true));
  const before = F.itemsFromCSV(rows, "ratings").map(i => i.raw.response_sha256);
  const after = F.itemsFromCSV(back, "ratings").map(i => i.raw.response_sha256);
  assert(before.join() === after.join(), "response_sha256 在导出后被改动");
  assert(after.every(v => /^[0-9a-f]{64}$/.test(v)), "导出的 response_sha256 不是 64 位十六进制");
  return "非法值报错、NA 规则正确、指纹保留";
});

check("responses.json 能补齐第二阶段的问句", () => {
  const rows = rowsOf("answer-review/ratings-A.csv");
  const items = F.itemsFromCSV(rows, "ratings");
  const responses = JSON.parse(read("answer-review/responses.json"));
  const missing = F.attachResponses(items, responses);
  assert(responses.length === 53, "responses.json 有 " + responses.length + " 条");
  assert(missing.length === 0, "有 " + missing.length + " 条模板行在 responses.json 里找不到");
  assert(items.every(item => (item.question || "").length > 0), "存在没有问句的行");
  assert(items.every(item => item.raw.response_sha256 === item.detail.response_sha256),
         "模板指纹与 responses.json 不一致");
  return "53 条问句与指纹全部对齐";
});

const failed = results.filter(row => row[0] === "FAIL");
for (const [status, name, note] of results) {
  console.log((status === "OK" ? "  ok   " : "  FAIL ") + name + (note ? "  [" + note + "]" : ""));
}
console.log("\n自测：" + (results.length - failed.length) + " 通过 / " + failed.length + " 失败");
process.exit(failed.length ? 1 : 0);
