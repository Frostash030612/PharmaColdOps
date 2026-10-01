// Run with Playwright CLI on a fresh isolated API page with the new-case modal open.
async (page) => {
  const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
  const panel=page.locator('.ni-body .m4-panel');
  const clickResponse=async (suffix,button,method='POST')=>{
    const [r]=await Promise.all([page.waitForResponse(r=>r.request().method()===method && new URL(r.url()).pathname.endsWith(suffix)),button.click()]);
    if(!r.ok()) throw new Error(`${suffix}: ${r.status()} ${await r.text()}`);
    return r.json();
  };
  const riskSamples=await clickResponse('/api/ml/samples/risk',panel.getByRole('button',{name:'加载留出集演示样本',exact:true}),'GET');
  await panel.locator('.m4-sample').selectOption(riskSamples.samples.at(-1).sample_id);
  const risk=await clickResponse('/api/ml/predict',panel.getByRole('button',{name:'调用训练模型',exact:true}));
  if(risk.status!=='predicted' || risk.target!=='silent_failure') throw new Error('real risk prediction missing');
  await panel.locator('.m4-attach input').check();
  await panel.getByRole('button',{name:'候选原因（月度上下文）',exact:true}).click();
  const causeSamples=await clickResponse('/api/ml/samples/cause',panel.getByRole('button',{name:'加载留出集演示样本',exact:true}),'GET');
  await panel.locator('.m4-sample').selectOption(causeSamples.samples[0].sample_id);
  let cause=await clickResponse('/api/ml/predict',panel.getByRole('button',{name:'调用训练模型',exact:true}));
  if(cause.status!=='predicted' || cause.top_classes.length!==3) throw new Error('cause candidates missing');
  await panel.locator('.m4-attach input').check();
  await panel.getByLabel('设备年限',{exact:true}).fill('10');
  if(await panel.locator('.m4-result').count() || await panel.locator('.m4-attach').count()) throw new Error('stale result survived input edit');
  await panel.locator('.m4-sample').selectOption(causeSamples.samples[0].sample_id);
  cause=await clickResponse('/api/ml/predict',panel.getByRole('button',{name:'调用训练模型',exact:true}));
  await panel.locator('.m4-attach input').check();
  const inputs=page.locator('.ni-body .range-line input[type=number]');
  for(const [i,value] of [[0,'5'],[1,'0'],[2,'5']]) await inputs.nth(i).fill(value);
  const record=await clickResponse('/api/case_close',page.getByRole('button',{name:'✓ 登记判定并归档',exact:true}));
  if(record.disposition!=='release' || record.reshipment_required || record.ml_assessments.length!==2) throw new Error('ML changed rule decision or snapshot missing');
  const saved=page.locator('.case-drawer .m4-panel');
  await saved.locator('.m4-result').nth(1).waitFor();
  if(await saved.locator('.m4-predict').count()) throw new Error('archive allowed re-evaluation');
  const savedText=await saved.innerText();
  if(!savedText.includes(risk.model_id) || !savedText.includes(cause.model_id)) throw new Error('saved model version missing');
  await page.locator('.case-drawer-head .modal-x').click();
  await page.reload();
  await page.locator('.incident-card').first().click();
  await page.locator('.case-drawer .m4-result').nth(1).waitFor();
  if(!(await page.locator('.case-drawer .m4-panel').innerText()).includes(risk.model_id)) throw new Error('reload lost model snapshot');
  await page.locator('.case-drawer-head .modal-x').click();
  let mlRequests=0; const observe=request=>{if(request.url().includes('/api/ml/')) mlRequests++;};
  page.on('request',observe);
  await page.getByRole('button',{name:'离线规则沙箱',exact:true}).click();
  await page.locator('.case-drawer .m4-panel').getByText(/离线规则沙箱不运行或模拟 ML/).waitFor();
  await page.locator('.case-drawer-head .modal-x').click();
  page.off('request',observe);
  if(mlRequests!==0 || errors.length) throw new Error(`offline requests=${mlRequests}; errors=${errors}`);
  await page.screenshot({path:`output/playwright/m4-${Date.now()}.png`,fullPage:true});
  return {status:'passed',run_id:record.run_id,risk_probability:risk.failure_probability,model_id:risk.model_id,
    cause_candidates:cause.top_classes,disposition:record.disposition,offline_ml_requests:mlRequests,errors};
}
