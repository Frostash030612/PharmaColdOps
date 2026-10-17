// Playwright CLI run-code --filename. Set URL hash to #video=<scene>.
// Isolated recording server only. Business writes use visible controls;
// no mocked replies, Pinia injection or fabricated review credentials.
async(page)=>{
  const api=new URL(page.url()).searchParams.get('api');
  if(!api||new URL(api).hostname!=='127.0.0.1'||['8080','8000'].includes(new URL(api).port))throw Error('isolated recording API required');
  const scene=new URL(page.url()).hash.replace('#video=','');
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const assert=(value,message)=>{if(!value)throw Error(message);};
  const hold=()=>page.waitForTimeout(2500);
  const focus=async locator=>{await locator.scrollIntoViewIfNeeded();const box=await locator.boundingBox();if(box)await page.mouse.move(box.x+box.width/2,box.y+Math.min(box.height/2,35),{steps:10});};
  const click=async locator=>{await focus(locator);await locator.click();await page.waitForTimeout(500);};
  const fill=async(locator,value)=>{await focus(locator);await locator.fill(value);await page.waitForTimeout(250);};
  const post=async(suffix,button)=>{
    const [r]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.endsWith(suffix)),click(button)]);
    assert(r.ok(),`${suffix}: ${r.status()} ${await r.text()}`);return r.json();
  };
  const get=async path=>{const r=await page.request.get(api+path);assert(r.ok(),`${path} ${r.status()}`);return r.json();};
  const current=async()=>{const runs=(await get('/api/dispatch/runs?limit=20')).runs;assert(runs.length===1,'one recording operation required');return get('/api/dispatch/runs/'+runs[0].dispatch_id);};
  const caseRecord=async()=>{const runs=(await get('/api/runs?limit=20')).runs;assert(runs.length===1,'one scripted recording case required');return runs[0];};
  let facts={scene,simulated:true,scripted_review_not_real_authorisation:true};
  if(scene==='generator'){
    assert((await get('/api/runs')).runs.length===0,'fresh case store required');
    await click(page.getByRole('button',{name:'Greedy',exact:true}));
    const panel=page.locator('.simulation-generator');
    await focus(panel.getByRole('heading'));
    await fill(panel.getByLabel('Delivery date',{exact:true}),'2026-10-17');
    await fill(panel.getByLabel('Random seed',{exact:true}),'41');
    await fill(panel.getByLabel('Orders / hospitals',{exact:true}),'4');
    await click(panel.getByText('Custom parameters',{exact:true}));
    await panel.locator('.sg-advanced select').nth(0).selectOption(['vaccine_2_8']);
    await panel.locator('.sg-advanced select').nth(1).selectOption(['W-WESTGATE']);
    for(const [label,value]of[['Min boxes per order','10'],['Max boxes per order','10'],['Min regular window (minutes)','480'],['Max regular window (minutes)','480'],['Available vehicles','3'],['Spare per vehicle per product (boxes)','20']])await fill(panel.getByLabel(label,{exact:true}),value);
    await click(panel.getByText('Custom parameters',{exact:true}));
    const result=await post('/api/dispatch/plan',panel.getByRole('button',{name:'Generate simulated orders and preview',exact:true}));
    assert(result.feasible,'simulated plan is infeasible');
    await click(panel.getByText(/View source orders/));await hold();
    facts={...facts,feasible:result.feasible,seed:41,order_count:4};
  }else if(scene==='parking'){
    const limits=page.locator('.sg-limits');await focus(limits);
    for(const [i,value]of[[0,'3'],[1,'150'],[2,'8']])await fill(limits.locator('input[type=number]').nth(i),value);
    const inputs=limits.locator('.sg-terminal input');assert(await inputs.count()===5,'exactly five parking warehouses');
    for(let i=0;i<5;i++){const input=inputs.nth(i),id=await input.getAttribute('value');assert(!id.startsWith('H-'),'hospital terminal');await input.setChecked(['D-NORTHPOINT','D-HOUGANG'].includes(id));}
    await hold();await post('/api/dispatch/plan',limits.getByRole('button',{name:'Apply and re-plan',exact:true}));
    const departure=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.endsWith('/depart'));
    const created=await post('/api/dispatch/runs',page.getByRole('button',{name:'Confirm plan and create the operation',exact:true}));
    assert((await departure).ok(),'departure failed');
    await click(page.getByRole('button',{name:'⛶ Expand map',exact:true}));
    await post('/speed',page.locator('.tv-controls').getByRole('button',{name:'⏸ Pause',exact:true}));
    await hold();await click(page.locator('.tv-close'));
    facts={...facts,dispatch_id:created.dispatch_id,terminal_facility_ids:created.input.constraints.terminal_facility_ids};
  }else if(scene==='urgent'){
    const operation=await current(),panel=page.locator('.urgent-panel');await focus(panel.getByRole('heading'));
    assert(await panel.locator('input[type=number]').count()===0,'quantity input in urgent entry');
    await panel.locator('.urgent-fields select').nth(2).selectOption('H-NUH');
    await fill(panel.getByLabel('Latest delivery (same day)',{exact:true}),'17:00');
    const preview=await post('/urgent-preview',panel.getByRole('button',{name:'Compare urgent delivery options',exact:true}));
    const index=preview.candidates.findIndex(c=>c.feasible);assert(index>=0,'no executable urgent option');
    await hold();await panel.locator(`input[name=urgent-candidate][value="${index}"]`).check();
    const accepted=await post('/urgent-accept',panel.getByRole('button',{name:'Use selected option and apply',exact:true}));
    assert(accepted.dispatch_id===operation.dispatch_id,'urgent operation changed');await hold();
    facts={...facts,dispatch_id:accepted.dispatch_id,quantity_input:false};
  }else if(scene==='incident'){
    const operation=await current();
    const original=operation.input.orders.find(o=>!o.source_run_id&&!o.order_id.startsWith('URG')&&operation.orders[o.order_id]?.status!=='delivered');
    assert(original,'original pending order required');
    await page.locator('header .header-plus').scrollIntoViewIfNeeded();await click(page.locator('header .header-plus'));
    const panel=page.locator('.ni-body');
    await panel.locator('.ctl select').nth(0).selectOption(original.order_id);
    await panel.locator('.ctl select').nth(1).selectOption('W-WESTGATE');
    for(const [i,value]of[[0,'20'],[1,'90'],[2,'19']])await fill(panel.locator('.range-line input[type=number]').nth(i),value);
    await panel.getByRole('checkbox',{name:'Request human review',exact:true}).check();
    await fill(panel.getByRole('textbox',{name:'Reason for review request',exact:true}),'Scripted recording fixture: demonstrate the review gate, not a real pharmaceutical decision.');
    await hold();const record=await post('/api/case_close',page.getByRole('button',{name:'✓ Register & archive',exact:true}));
    assert(record.review_status==='pending'&&record.event.dispatch_id===operation.dispatch_id,'review/association missing');
    const review=page.locator('.case-drawer .review-panel');await focus(review);await hold();
    const button=page.locator('.case-actions').getByRole('button',{name:'Start handling',exact:true});
    assert(await button.isDisabled(),'pending review did not block execution');
    facts={...facts,run_id:record.run_id,original:record.disposition,review_status:record.review_status,execution_blocked:true};
  }else if(scene==='pending'){
    // Resume a captured registration after a locator-only assertion failure;
    // do not register a second case or mutate its outcome.
    const record=await caseRecord();assert(record.review_status==='pending','pending review required');
    const button=page.locator('.case-actions').getByRole('button',{name:'Start handling',exact:true});
    assert(await button.isDisabled(),'pending review did not block execution');
    await focus(page.locator('.case-drawer .review-panel'));await hold();
    facts={...facts,scene:'incident',run_id:record.run_id,original:record.disposition,
      review_status:record.review_status,execution_blocked:true,resumed_read_only_verification:true};
  }else if(scene==='review'){
    const record=await caseRecord(),review=page.locator('.case-drawer .review-panel');await focus(review);
    await fill(review.getByRole('textbox',{name:'Reviewer (self-declared demo name)',exact:true}),'SCRIPTED DEMO - not a real quality reviewer');
    await review.getByRole('combobox',{name:'Review outcome',exact:true}).selectOption('scrap');
    await fill(review.getByRole('textbox',{name:'Review rationale / references / checks performed',exact:true}),'Scripted UI demonstration on simulated data only. This illustrates a separate review record; no real batch, qualified reviewer or medicine authorisation is claimed.');
    await hold();const reviewed=await post(`/api/runs/${record.run_id}/review`,review.getByRole('button',{name:'Save human review outcome',exact:true}));
    assert(reviewed.effective_disposition==='scrap'&&reviewed.review_status!=='pending','review state unresolved');
    const actions=page.locator('.case-actions');
    const preview=await post('/api/dispatch/reshipments/preview',actions.getByRole('button',{name:'Compare delivery options here',exact:true}));
    const index=preview.candidates.findIndex(c=>c.feasible);assert(index>=0,'replacement infeasible');await hold();
    const accepted=await post('/api/dispatch/reshipments',actions.locator('.workflow-options tbody tr').nth(index).getByRole('button',{name:'Use this option',exact:true}));
    await focus(review);await hold();await click(page.locator('.case-drawer-head .modal-x'));
    facts={...facts,run_id:record.run_id,original:reviewed.disposition,effective:reviewed.effective_disposition,
      review_count:reviewed.review_history.length,dispatch_id:accepted.dispatch_id,executed_replacement:true};
  }else if(scene==='delivery'){
    const operation=await current(),record=await caseRecord();
    await click(page.getByRole('button',{name:'⛶ Expand map',exact:true}));
    await post('/speed',page.locator('.tv-controls').getByRole('button',{name:'300x',exact:true}));
    await page.waitForResponse(async r=>{
      if(!new URL(r.url()).pathname.endsWith('/tick')||!r.ok())return false;
      const body=await r.json();return body.status==='completed'&&body.route_view.metrics.still_returning===0;
    },{timeout:120000});
    await hold();const done=await get('/api/dispatch/runs/'+operation.dispatch_id);
    assert(done.orders['RO-'+record.run_id]?.status==='delivered','replacement was not delivered by real ticks');
    await page.screenshot({path:'output/playwright/video-20261017/delivered.png'});await click(page.locator('.tv-close'));
    facts={...facts,run_id:record.run_id,dispatch_id:operation.dispatch_id,replacement_status:'delivered',simulation_speed:300};
  }else if(scene==='qa'){
    const record=await caseRecord(),qa=page.locator('.qa-query-kind').locator('..');
    if(!(await qa.locator('.qa-context').innerText()).includes(record.run_id)){
      await click(page.locator('.hist-row').filter({hasText:record.run_id}).first());await click(page.locator('.case-drawer-head .modal-x'));
    }
    await focus(qa.locator('.qa-query-kind'));await qa.getByRole('combobox').selectOption('audit_chain');
    const answer=await post('/api/qa',qa.getByRole('button',{name:'Ask',exact:true}));
    assert(answer.status==='ok'&&answer.evidence.some(e=>e.node_id===record.run_id),'case-specific graph evidence missing');
    await focus(qa.locator('.answer'));await hold();
    await focus(qa.locator('.qa-evidence'));await hold();
    await qa.getByRole('combobox').selectOption('auto');await fill(qa.locator('.qline input'),'What will the weather be tomorrow?');
    await click(qa.getByRole('button',{name:'Ask',exact:true}));
    assert((await qa.locator('.qa-source').innerText()).includes('Unsupported'),'refusal missing');await hold();
    facts={...facts,run_id:record.run_id,graph_evidence:true,recorded_source_links:answer.evidence.filter(e=>e.source_url).length,unsupported_refused:true};
  }else if(scene==='audit'){
    const record=await caseRecord();await click(page.locator('.incident-card').first());
    const actions=page.locator('.case-actions');
    await fill(actions.locator('.workflow-note textarea'),'Scripted recording fixture: replacement delivered by the simulated clock; close this demonstration incident.');
    const closed=await post(`/api/runs/${record.run_id}/workflow`,actions.getByRole('button',{name:'Close incident',exact:true}));
    assert(closed.processing_status==='closed','closure failed');
    const review=page.locator('.case-drawer .review-panel');await focus(review.locator('.audit-exports'));await hold();
    const [download]=await Promise.all([page.waitForEvent('download'),click(review.getByRole('link',{name:'Download HTML audit report',exact:true}))]);
    await download.saveAs('output/playwright/video-20261017/demo-audit.html');
    const audit=await get(`/api/runs/${record.run_id}/audit?format=json`);
    assert(audit.original_registration&&audit.effective_assessment&&audit.delivery,'audit data incomplete');
    await hold();await click(page.locator('.case-drawer-head .modal-x'));
    facts={...facts,run_id:record.run_id,closed:closed.processing_status,audit_download:true,graph:audit.graph.status};
  }else if(scene==='parking-offline'){
    const preview=await post('/overnight-preview',page.getByRole('button',{name:'Review tonight\'s parking and tomorrow\'s fixed plan',exact:true}));
    assert(preview.feasible,'parking preview infeasible');await hold();
    await page.getByRole('button',{name:'Offline rule sandbox',exact:true}).scrollIntoViewIfNeeded();
    await click(page.getByRole('button',{name:'Offline rule sandbox',exact:true}));
    assert(await page.locator('.case-actions').count()===0,'offline execution actions exposed');await hold();
    await page.screenshot({path:'output/playwright/video-20261017/offline.png'});await click(page.locator('.case-drawer-head .modal-x'));
    facts={...facts,parking_preview_feasible:true,parking_preview_not_adopted:true,offline_read_only:true};
  }else throw Error('unknown recording scene: '+scene);
  assert(errors.length===0,JSON.stringify(errors));
  return{status:'captured',...facts,page_errors:errors};
}
