import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { v2Context, matchesV2Temperature, eventReasonLabel } from '../frontend-vue/src/lib/eventV2.js';
import { eventPayload, decisionKey } from '../frontend-vue/src/lib/api.js';
const observation = { product_id:'vaccine_2_8', event_id:'EV-demo', observation_end_min:5,
  records:[{start_min:0,end_min:5,product_temp_c:5,humidity_pct:50}] };
const series = { source:'simulated',observation_end_min:5,activation_energy_kj_mol:83.144,
  intervals:[{start_min:0,end_min:5,temp_c:5}] };
const result = {status:'abstained',product_id:'vaccine_2_8',event_id:'EV-demo',shadow_only:true,review_required:true,
  automatic_actions_allowed:false,temperature_series:series,model_sha256:'model',policy_sha256:'policy'};
const adopted = v2Context(result,observation,'vaccine_2_8');
assert.deepEqual(adopted.event,{excursion_temp_c:null,duration_min:null,mkt_c:null});
assert.equal(adopted.temperatureContext.window_id,null);
assert.ok(matchesV2Temperature(series,observation));
const base={product_id:'vaccine_2_8',excursion_temp_c:12,duration_min:30,mkt_c:12,packaging:'intact',stage:'transit'};
const spec={allowable:30,mktThreshold:10,retestable:true};
const attached={...base,event_v2_context:adopted.eventContext,temperature_context:adopted.temperatureContext};
assert.notEqual(decisionKey(base,spec),decisionKey(attached,spec));
assert.equal(eventPayload(base).event_v2_context,undefined);
const body=eventPayload(attached);
adopted.eventContext.observation.records[0].humidity_pct=60;
assert.equal(body.event_v2_context.observation.records[0].humidity_pct,50);
assert.notEqual(decisionKey({...attached,event_v2_context:body.event_v2_context},spec),decisionKey(attached,spec));
assert.equal(eventPayload({...attached,event_v2_context:null}).event_v2_context,undefined);
for(const override of [{status:'disabled'},{status:'unavailable'},{review_required:false},{automatic_actions_allowed:true},
  {shadow_only:false},{product_id:'insulin_2_8'},{event_id:'other'},{temperature_series:{...series,observation_end_min:6}}]) {
  assert.throws(()=>v2Context({...result,...override},observation,'vaccine_2_8'));
}
for(const lang of ['en','zh']) {
  const L=new Function(readFileSync(`frontend-vue/src/i18n/${lang}.js`,'utf8').replace(/^export default/m,'return'))();
  for(const key of ['candidate_only','abstained','disabled','unavailable']) assert.equal(typeof L.eventV2.status[key],'string');
  assert.equal(eventReasonLabel('event_model_human_confirmation_required',L.eventV2.reasons),L.eventV2.reasons.human_confirmation_required);
  assert.equal(eventReasonLabel('event_v2_event_v2_shadow_disabled',L.eventV2.reasons),L.eventV2.reasons.event_v2_shadow_disabled);
}
console.log('V2 adoption, immutable payload, complete-temperature binding, cache identity, forbidden authority and bilingual reasons passed.');
