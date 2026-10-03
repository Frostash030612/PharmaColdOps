// Exact production router and fallback, not a second keyword implementation.
import { classifyQuestion, askKG } from '../frontend-vue/src/lib/qa.js';
import en from '../frontend-vue/src/i18n/en.js';
import zh from '../frontend-vue/src/i18n/zh.js';
let text='';for await(const chunk of process.stdin)text+=chunk;
const rows=JSON.parse(text);
process.stdout.write(JSON.stringify(rows.map(row=>({question_id:row.question_id,
  predicted_intent:classifyQuestion(row.question)||'unsupported',
  fallback:askKG(row.question,row.lang==='zh'?zh:en)}))));
