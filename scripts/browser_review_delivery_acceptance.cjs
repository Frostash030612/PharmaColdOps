// Playwright CLI: isolated API page, no active delivery operation, no drawer open.
async(page)=>{
  const assert=(ok,m)=>{if(!ok)throw new Error(m);};
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const clickResponse=async(suffix,button)=>{
    const [r]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.endsWith(suffix)),button.click()]);
    assert(r.ok(),`${suffix}: ${r.status()} ${await r.text()}`);return r.json();
  };
  await page.getByRole('button',{name:'中文',exact:true}).click();
  await page.getByRole('button',{name:'贪心方案',exact:true}).click();
  const generator=page.locator('.simulation-generator');
  await generator.getByLabel('配送日期',{exact:true}).fill('2026-10-03');
  await generator.getByLabel('随机种子',{exact:true}).fill('41');
  await generator.getByLabel('订单数／医院数',{exact:true}).fill('4');
  await generator.getByText('可调参数',{exact:true}).click();
  await generator.locator('.sg-advanced select').nth(0).selectOption(['vaccine_2_8']);
  await generator.locator('.sg-advanced select').nth(1).selectOption(['W-WESTGATE']);
  for(const [label,value]of[['每单最少箱数','10'],['每单最多箱数','10'],['普通时间窗最短（分钟）','480'],['普通时间窗最长（分钟）','480'],['可用车数','3'],['每车每品类备用量（箱）','20']])await generator.getByLabel(label,{exact:true}).fill(value);
  const preview=await clickResponse('/api/dispatch/plan',generator.getByRole('button',{name:'生成模拟订单并预览',exact:true}));
  assert(preview.feasible,'demo plan infeasible');
  const departure=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.endsWith('/depart'));
  const created=await clickResponse('/api/dispatch/runs',page.getByRole('button',{name:'确认该计划并建立配送作业',exact:true}));
  assert((await departure).ok(),'departure failed');
  await page.getByRole('button',{name:'⛶ 展开地图',exact:true}).click();
  await clickResponse('/speed',page.locator('.tv-controls').getByRole('button',{name:'⏸ 暂停',exact:true}));
  await page.locator('.tv-close').click();
  await page.locator('header .header-plus').click();
  const modal=page.locator('.ni-body');
  await modal.locator('.ctl select').nth(0).selectOption(created.input.orders[0].order_id);
  await modal.locator('.ctl select').nth(1).selectOption('W-WESTGATE');
  for(const [i,value]of[[0,'5'],[1,'0'],[2,'5']])await modal.locator('.range-line input[type=number]').nth(i).fill(value);
  await modal.getByRole('checkbox',{name:'主动申请人工审核',exact:true}).check();
  await modal.getByRole('textbox',{name:'申请审核原因',exact:true}).fill('演示：主动独立复核，保留原始正常输入。');
  const record=await clickResponse('/api/case_close',page.getByRole('button',{name:'✓ 登记判定并归档',exact:true}));
  assert(record.disposition==='release'&&record.review_status==='pending','original suggestion / pending review not separated');
  const review=page.locator('.case-drawer .review-panel');
  await review.getByRole('textbox',{name:'审核人（演示自报姓名）',exact:true}).fill('演示审核人 Bob');
  await review.getByRole('combobox',{name:'审核结论',exact:true}).selectOption('scrap');
  await review.getByRole('textbox',{name:'审核理由／参考资料／实际核查说明',exact:true}).fill('仿真人工复核：模拟发现原输入遗漏风险，选择报废补发；不是实际药品判断。');
  const manual=await clickResponse(`/api/runs/${record.run_id}/review`,review.getByRole('button',{name:'保存人工审核结论',exact:true}));
  assert(manual.disposition==='release'&&manual.effective_disposition==='scrap'&&manual.effective_reshipment_required,'manual outcome did not become execution authority');
  const actions=page.locator('.case-actions');
  const options=await clickResponse('/api/dispatch/reshipments/preview',actions.getByRole('button',{name:'在此比较配送方案',exact:true}));
  const index=options.candidates.findIndex(c=>c.feasible);
  assert(index>=0,'no feasible reviewed reshipment');
  const result=await clickResponse('/api/dispatch/reshipments',actions.locator('.workflow-options tbody tr').nth(index).getByRole('button',{name:'采用此方案',exact:true}));
  assert(result.dispatch_id===created.dispatch_id&&result.orders[`RO-${record.run_id}`],'reshipment not attached to original operation');
  await review.getByText(/已执行补发或已完成处理/).waitFor();
  assert(await review.getByRole('button',{name:'保存人工审核结论',exact:true}).count()===0,'executed human verdict still editable');
  const audit=await(await page.request.get(`http://127.0.0.1:18004/api/runs/${record.run_id}/audit?format=json`)).json();
  assert(audit.original_registration.disposition==='release'&&audit.effective_assessment.effective_disposition==='scrap'&&audit.delivery.orders[`RO-${record.run_id}`],'audit did not preserve original versus executed facts');
  await review.scrollIntoViewIfNeeded();await page.screenshot({path:`output/playwright/review-delivery-${Date.now()}.png`});
  await page.locator('.case-drawer-head .modal-x').click();
  assert(errors.length===0,`page errors:${errors}`);
  return{status:'passed',run_id:record.run_id,dispatch_id:created.dispatch_id,original:'release',effective:'scrap',
    replacement_order:`RO-${record.run_id}`,execution_locked:true,graph:audit.graph.status,errors};
}
