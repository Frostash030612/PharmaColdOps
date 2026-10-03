import assert from 'node:assert/strict';
import { incidentStatus, filterIncidents } from '../frontend-vue/src/lib/incidentWorkflow.js';
const record = {run_id:'R1',created_at:'2026-10-03',event:{dispatch_id:'PLAN',order_id:'O1'},disposition:'release',reshipment_required:false,
  review_status:'resolved',effective_disposition:'scrap',effective_reshipment_required:true,effective_destination_facility_id:'H-SGH',processing_status:'pending'};
const run = {dispatch_id:'PLAN',orders:{'RO-R1':{order_id:'RO-R1',status:'delivered'}}};
assert.equal(incidentStatus(record,run),'handled');
assert.equal(incidentStatus({...record,review_status:'pending'},run),'pending');
assert.equal(incidentStatus({...record,effective_reshipment_required:false},run),'pending');
assert.equal(filterIncidents([record],{hospital:'H-SGH'},run).length,1);
assert.equal(filterIncidents([record],{hospital:'H-NUH'},run).length,0);
assert.equal(incidentStatus({reshipment_required:true,processing_status:'closed'},run),'closed');
console.log('Human review pending gates, effective reshipment, actual delivery and reviewed hospital filters passed.');
