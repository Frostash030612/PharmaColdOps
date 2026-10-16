/* Developer-authored behavioural regressions, not independent human evaluation. */
import assert from 'node:assert/strict';
import zh from '../frontend-vue/src/i18n/zh.js';
import en from '../frontend-vue/src/i18n/en.js';
import { classifyQuestion, conceptAnswer, askKG, safeEvidenceLink, decodeQaResponse, QA_QUERY_TYPES, questionScopeMismatch } from '../frontend-vue/src/lib/qa.js';

const routing = [
  ['Why was this case released?', 'why_disposition'],
  ['为什么这个案例被判定报废？', 'why_disposition'],
  ['Show the audit trail for the selected case', 'audit_chain'],
  ['请追溯这个案例的全过程', 'audit_chain'],
  ['What are the product storage requirements?', 'product_requirements'],
  ['该产品的允许时长是什么', 'product_requirements'],
  ['Show disposition statistics for recorded cases', 'disposition_stats'],
  ['统计所有归档案例的处置分布', 'disposition_stats'],
  ['In which stages is this recorded cause common?', 'cause_context'],
  ['Why is this recorded cause common across products?', 'cause_context'],
  ['这个原因最常见于哪些运输阶段？', 'cause_context'],
  ['Why will it rain tomorrow?', null],
  ['Certify actual potency of this vaccine brand', null],
  ['能否确认真实效价？', null],
  ['Show the audit chain and product storage requirements', null],
  ['mkt', null], ['latest update', null], ['threshold', null],
];
for (const [question, type] of routing) assert.equal(classifyQuestion(question), type, question);
for (const L of [zh, en]) {
  for (const q of ['What will the weather be tomorrow?', '今天的天气好吗？', 'Certify actual potency of this vaccine brand', '能否确认这支疫苗的真实效价？']) {
    assert.equal(askKG(q, L), L.right.qaStatus_unsupported);
    assert.equal(conceptAnswer(q, L), null);
  }
  for (const type of QA_QUERY_TYPES) assert.equal(typeof L.right[`qaQuery_${type}`], 'string');
  assert.equal(decodeQaResponse({status:'no_case', answer:'no case', evidence:[]}, L).source, 'notice');
  assert.equal(decodeQaResponse({status:'ok', answer:'no aggregate entries', evidence:[]}, L).source, 'live');
  assert.throws(()=>decodeQaResponse({answer:'untyped text', evidence:[]}, L));
  assert.throws(()=>decodeQaResponse({status:'ok', answer:'x', evidence:[{node_type:'Regulation'}]}, L));
}
assert.equal(conceptAnswer('Who approved the batch?', en), null);
assert.equal(conceptAnswer('latest', en), null);
assert.equal(conceptAnswer('threshold', en), null); // must not match the keyword "hold"
assert.equal(conceptAnswer('release and scrap', en), null);
assert.match(askKG('scrap', en), /applicable product stability evidence/);
assert.doesNotMatch(askKG('retest', en), /Retesting confirms potency/);
assert.match(askKG('报废', zh), /稳定性资料/);
for (const url of ['javascript:alert(1)', 'file:///tmp/a', 'data:text/html,x', 'ftp://example.org/a', 'https://u:p@example.org/a', 'relative/path']) {
  assert.equal(safeEvidenceLink(url), null);
}
assert.equal(safeEvidenceLink('https://example.org/source'), 'https://example.org/source');
const context={runId:'R20261017-120000-123456-aabbccdd',productId:'vaccine_2_8'};
assert.equal(questionScopeMismatch('Insulin storage requirements','product_requirements',context),true);
assert.equal(questionScopeMismatch('vaccine_2_8 storage requirements','product_requirements',context),false);
assert.equal(questionScopeMismatch('Why R20261017-120000-123456-11223344?','why_disposition',context),true);
assert.equal(questionScopeMismatch('vaccine_2_8 disposition statistics','disposition_stats',context),true);
console.log(`QA routing ${routing.length} cases, scoped refusal, concept boundaries, response contracts and safe source links passed. Developer regressions only.`);
