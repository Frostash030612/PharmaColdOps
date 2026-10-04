// LIVE instance: read-only previews only. Never click archive/review/dispatch.
async(page)=>{
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const runsUrl=new URL('/api/runs?limit=200',page.url()).href;
  const before=await page.request.get(runsUrl).then(r=>r.json());
  await page.reload();
  await page.getByRole('button',{name:'+',exact:true}).click();
  const panel=page.locator('.ni-body .event-v2-panel');
  const overlayLayer=await page.locator('.modal-overlay').evaluate(el=>Number(getComputedStyle(el).zIndex));
  const mapLayers=await page.locator('.sg-fit').evaluateAll(els=>els.map(el=>Number(getComputedStyle(el).zIndex)));
  if(mapLayers.some(layer=>layer>=overlayLayer))throw new Error('map controls can overlay model input');
  const clickRead=async(path,button,method='POST')=>{
    const [r]=await Promise.all([page.waitForResponse(r=>r.request().method()===method&&new URL(r.url()).pathname===path),button.click()]);
    if(!r.ok())throw new Error(`${path} ${r.status()}`);return r.json();
  };
  await clickRead('/api/ml/event/v2/samples',panel.getByRole('button',{name:'检查开关并加载 v2 演示样本',exact:true}),'GET');
  const results=[];
  for(const id of ['test_nominal-0002','test_scenario-0005']){
    await panel.getByRole('combobox').selectOption(id);
    const result=await clickRead('/api/ml/event/v2/assess',panel.getByRole('button',{name:'只读预览 v2 候选',exact:true}));
    if(!result.review_required||result.automatic_actions_allowed||result.feature_count!==111)throw new Error('review boundary wrong');
    results.push({sample_id:id,status:result.status,model_id:result.model_id});
  }
  await panel.screenshot({path:'output/playwright/v2-live-update-20261004/live-panel.png'});
  // Only close the client draft: no registration occurs.
  await page.getByRole('button',{name:'取消',exact:true}).click();
  const after=await page.request.get(runsUrl).then(r=>r.json());
  if(JSON.stringify(before)!==JSON.stringify(after)||errors.length)throw new Error('records changed or component error');
  return {status:'passed',previews:results,registered_test_cases:0,case_response_unchanged:true,page_errors:errors};
}
