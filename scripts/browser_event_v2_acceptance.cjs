// Use Playwright CLI against a NEW isolated API/storage, never user data.
async (page) => {
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const responseClick=async(path,button,method='POST')=>{
    const [response]=await Promise.all([page.waitForResponse(r=>r.request().method()===method && new URL(r.url()).pathname===path),button.click()]);
    if(!response.ok()) throw new Error(`${path}: ${response.status()} ${await response.text()}`);
    return response.json();
  };
  await page.reload();
  await page.getByRole('button',{name:'+',exact:true}).click();
  const panel=page.locator('.ni-body .event-v2-panel');
  const sampleId=new URL(page.url()).searchParams.get('v2_accept_sample') || 'test_nominal-0002';
  await responseClick('/api/ml/event/v2/samples',panel.getByRole('button',{name:'检查开关并加载 v2 演示样本',exact:true}),'GET');
  await panel.getByRole('combobox').selectOption(sampleId);
  let preview=await responseClick('/api/ml/event/v2/assess',panel.getByRole('button',{name:'只读预览 v2 候选',exact:true}));
  if(preview.feature_count!==111 || !preview.review_required || preview.automatic_actions_allowed) throw new Error('incorrect v2 contract');
  const raw=panel.getByRole('textbox',{name:'v2 公开观测 JSON',exact:true});
  const edited=JSON.parse(await raw.inputValue());edited.records[0].humidity_pct+=1;
  await raw.fill(JSON.stringify(edited,null,2));
  if(await panel.locator('.event-v2-result').count()) throw new Error('stale result survived input edit');
  preview=await responseClick('/api/ml/event/v2/assess',panel.getByRole('button',{name:'只读预览 v2 候选',exact:true}));
  await panel.getByRole('button',{name:'采用完整观测并转人工登记',exact:true}).click();
  await panel.getByText('已附加 v2 完整模拟观测；编辑后需重新预览／采用。',{exact:true}).waitFor();
  const record=await responseClick('/api/case_close',page.getByRole('button',{name:'✓ 登记判定并归档',exact:true}));
  if(record.review_status!=='pending' || record.effective_disposition!==null || record.automatic_assessment_available!==false ||
     record.event.excursion_temp_c!==null || record.event.mkt_c!==null || record.event_v2_assessment.model_sha256!==preview.model_sha256 ||
     record.event_v2_assessment.observation_sha256!==preview.observation_sha256 || record.event_v2_context.observation.records[0].humidity_pct!==edited.records[0].humidity_pct) throw new Error('snapshot or review bypass');
  const saved=page.locator('.case-drawer .event-v2-panel');
  await saved.getByText(preview.model_id,{exact:false}).waitFor();
  if(await saved.getByRole('button').count()) throw new Error('history allowed model re-evaluation');
  await page.screenshot({path:'output/playwright/event-v2-shadow-20261004/shadow-pending.png',fullPage:true});
  const review=page.locator('.case-drawer .review-panel');
  await review.getByRole('textbox').first().fill('V2 浏览器演示审核人');
  await review.getByRole('combobox').first().selectOption('release');
  await review.getByRole('textbox').last().fill('独立复核完整模拟观测；模型候选不作为自动处置或配送授权');
  const updated=await responseClick(`/api/runs/${record.run_id}/review`,review.getByRole('button',{name:'保存人工审核结论',exact:true}));
  if(updated.effective_disposition!=='release' || updated.decision_source!=='manual_review' ||
     updated.event_v2_assessment.model_sha256!==record.event_v2_assessment.model_sha256) throw new Error('review authority or frozen history wrong');
  await page.locator('.case-drawer-head .modal-x').click();
  await page.reload();
  await page.locator('.incident-card').first().click();
  await page.locator('.case-drawer .event-v2-panel').getByText(preview.model_id,{exact:false}).waitFor();
  await page.locator('.case-drawer-head .modal-x').click();
  let calls=0;const monitor=r=>{if(r.url().includes('/api/ml/event/v2/')) calls++;};page.on('request',monitor);
  await page.getByRole('button',{name:'离线规则沙箱',exact:true}).click();
  await page.locator('.case-drawer .event-v2-panel').getByText('离线模式不调用或模拟 v2 模型。',{exact:true}).waitFor();
  if(await page.locator('.case-drawer .event-v2-panel').getByRole('button').count()) throw new Error('offline model controls visible');
  await page.locator('.case-drawer-head .modal-x').click();page.off('request',monitor);
  if(calls!==0 || errors.length) throw new Error(`offline calls=${calls},pageerrors=${errors}`);
  return {status:'passed',run_id:record.run_id,model_id:preview.model_id,preview_status:preview.status,
    edited_result_invalidated:true,full_observation_registered:true,review_required:true,human_release_effective:true,
    frozen_snapshot_after_reload:true,offline_model_requests:calls,page_errors:errors};
}
