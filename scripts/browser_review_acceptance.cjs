// Playwright CLI run-code --filename, isolated API, new-case modal open (ZH).
async (page) => {
  await page.unroute('**/api/runs/*/review'); // discard this test's leaked fault interceptor after a failed run
  const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
  const assert=(value,message)=>{if(!value)throw new Error(message);};
  const clickResponse=async(path,button)=>{
    const [response]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST' && new URL(r.url()).pathname===path),button.click()]);
    assert(response.ok(),`${path}: ${response.status()} ${await response.text()}`); return response.json();
  };
  await page.setViewportSize({width:1366,height:1000});
  const panel=page.locator('.ni-body .m2-panel');
  await panel.getByRole('button',{name:'序列计算',exact:true}).click();
  await panel.locator('summary').click();
  await panel.getByLabel('温度区间 JSON',{exact:true}).fill(JSON.stringify([{start_min:0,end_min:60,temp_c:null},{start_min:60,end_min:120,temp_c:null}]));
  const analysis=await clickResponse('/api/m2/analyse',panel.getByRole('button',{name:'分析编辑后的序列',exact:true}));
  assert(analysis.known_only_mkt_c===null && analysis.coverage_ratio===0,'all-missing data fabricated MKT');
  await panel.getByRole('button',{name:'登记整段观察，转人工审核',exact:true}).click();
  assert(await page.locator('.ni-body .range-line').count()===0,'unknown scalar controls still present');
  const record=await clickResponse('/api/case_close',page.getByRole('button',{name:'✓ 登记判定并归档',exact:true}));
  assert(record.automatic_assessment_available===false && record.event.mkt_c===null && record.review_status==='pending','observation not held honestly');
  let review=page.locator('.case-drawer .review-panel');
  await review.getByRole('button',{name:'保存人工审核结论',exact:true}).waitFor();
  assert(await page.locator('.case-drawer .dispo-banner').count()===0,'unassessed observation rendered automatic banner');
  assert(await page.locator('.case-actions').getByRole('button',{name:'开始处理',exact:true}).isDisabled(),'review bypass enabled');
  await review.getByRole('textbox',{name:'审核人（演示自报姓名）',exact:true}).fill('演示审核人 Alice');
  await review.getByRole('textbox',{name:'审核理由／参考资料／实际核查说明',exact:true}).fill('演示验收：全部缺测，先保持扣留待审核。');
  const held=await clickResponse(`/api/runs/${record.run_id}/review`,review.getByRole('button',{name:'保存人工审核结论',exact:true}));
  assert(held.review_status==='pending' && held.review_history.length===1,'continue hold resolved improperly');
  await review.getByRole('combobox',{name:'审核结论',exact:true}).selectOption('release');
  await review.getByRole('textbox',{name:'审核理由／参考资料／实际核查说明',exact:true}).fill('演示验收：人工选择放行展示闭环，不代表实际药品安全。');
  let committed;
  const lost=async route=>{const r=await route.fetch(); assert(r.ok(),await r.text()); committed=await r.json(); await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Review acceptance: response lost after commit'})});};
  await page.route('**/api/runs/*/review',lost);
  try {
    await Promise.all([page.waitForResponse(r=>r.request().method()==='POST' && new URL(r.url()).pathname.endsWith('/review') && r.status()===503),
      review.getByRole('button',{name:'保存人工审核结论',exact:true}).click()]);
    await review.getByRole('button',{name:'重试同一审核',exact:true}).waitFor();
  } finally { await page.unroute('**/api/runs/*/review',lost); }
  await page.reload(); await page.locator('.incident-card').first().click();
  review=page.locator('.case-drawer .review-panel');
  const resolved=await clickResponse(`/api/runs/${record.run_id}/review`,review.getByRole('button',{name:'重试同一审核',exact:true}));
  assert(resolved.review_history.length===2 && resolved.workflow_version===committed.workflow_version && resolved.effective_disposition==='release','review retry duplicated or lost outcome');
  const reportResponse=await page.request.get(`http://127.0.0.1:18004/api/runs/${record.run_id}/audit?format=json`);
  assert(reportResponse.ok(),'audit snapshot failed'); const report=await reportResponse.json();
  assert(report.original_registration.event.mkt_c===null && report.effective_assessment.effective_disposition==='release' && report.graph.status==='passed','audit lost original/effective/graph facts');
  const [jsonDownload]=await Promise.all([page.waitForEvent('download'),review.getByRole('link',{name:'下载完整审计 JSON',exact:true}).click()]);
  const jsonPath=`output/playwright/review-audit-${Date.now()}.json`; await jsonDownload.saveAs(jsonPath);
  const [htmlDownload]=await Promise.all([page.waitForEvent('download'),review.getByRole('link',{name:'下载审计报告 HTML',exact:true}).click()]);
  const htmlPath=`output/playwright/review-audit-${Date.now()}.html`; await htmlDownload.saveAs(htmlPath);
  await review.scrollIntoViewIfNeeded(); await page.screenshot({path:`output/playwright/review-panel-${Date.now()}.png`});
  const actions=page.locator('.case-actions');
  await actions.locator('.workflow-note textarea').fill('演示核查处理完毕；保留缺测事实及人工结论。');
  const handled=await clickResponse(`/api/runs/${record.run_id}/workflow`,actions.getByRole('button',{name:'确认处置完成',exact:true}));
  assert(handled.processing_status==='handled' && handled.review_history.length===2,'handling lost review audit');
  await actions.locator('.workflow-note textarea').fill('演示结案，非实际药品处置授权。');
  const closed=await clickResponse(`/api/runs/${record.run_id}/workflow`,actions.getByRole('button',{name:'确认结案',exact:true}));
  assert(closed.processing_status==='closed' && await review.getByRole('button',{name:'保存人工审核结论',exact:true}).count()===0,'closed review not locked');
  await page.locator('.case-drawer-head .modal-x').click(); await page.getByRole('button',{name:'EN',exact:true}).click();
  await page.locator('.incident-card').first().click();
  assert((await page.locator('.case-drawer .review-panel').innerText()).includes('Human review and case audit'),'English review missing');
  await page.locator('.case-drawer-head .modal-x').click();
  assert(errors.length===0,`page errors: ${errors}`);
  return {status:'passed',run_id:record.run_id,original_mkt:null,effective_disposition:resolved.effective_disposition,
    reviews:resolved.review_history.length,retry_same_version:true,graph:report.graph.status,content_sha256:report.content_sha256,
    closed:closed.processing_status,jsonPath,htmlPath,errors};
}
