// Playwright CLI run-code --filename scripts/browser_demo_acceptance.cjs
// Requires a FRESH isolated API database and an open Chinese Vue page.
// Business writes come exclusively from visible controls. Responses are observed,
// never replaced, and no Pinia state is injected.
async (page) => {
  const checks = [];
  const check = (name, value) => { if (!value) throw new Error(name); checks.push(name); };
  const postByClick = async (suffix, locator) => {
    console.log(`step: ${suffix}`);
    const [response] = await Promise.all([
      page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith(suffix)),
      locator.click(),
    ]);
    const body = await response.json();
    if (!response.ok()) throw new Error(`${suffix}: ${response.status()} ${JSON.stringify(body)}`);
    return body;
  };
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.getByRole('button', { name: '中文', exact: true }).click();
  await page.getByRole('button', { name: '贪心方案', exact: true }).click();
  const generator = page.locator('.simulation-generator');
  await generator.getByLabel('配送日期', { exact: true }).fill('2026-10-01');
  await generator.getByLabel('随机种子', { exact: true }).fill('41');
  await generator.getByLabel('订单数／医院数', { exact: true }).fill('4');
  if (await generator.locator('.sg-advanced').getAttribute('open') === null) await generator.getByText('可调参数', { exact: true }).click();
  await generator.locator('.sg-advanced select').nth(0).selectOption(['vaccine_2_8']);
  await generator.locator('.sg-advanced select').nth(1).selectOption(['W-WESTGATE']);
  for (const [label, value] of [['每单最少箱数', '10'], ['每单最多箱数', '10'], ['普通时间窗最短（分钟）', '480'],
    ['普通时间窗最长（分钟）', '480'], ['可用车数', '3'], ['每车每品类备用量（箱）', '20']]) {
    await generator.getByLabel(label, { exact: true }).fill(value);
  }
  const generated = await postByClick('/api/dispatch/plan', generator.getByRole('button', { name: '生成模拟订单并预览', exact: true }));
  check('fixed-seed generation is feasible', generated.feasible);
  const limits = page.locator('.sg-limits');
  await limits.locator('input[type=number]').nth(0).fill('3');
  await limits.locator('input[type=number]').nth(1).fill('150');
  await limits.locator('input[type=number]').nth(2).fill('8');
  const terminals = limits.locator('.sg-terminal input');
  check('parking picker has exactly five warehouses', await terminals.count() === 5);
  for (let i = 0; i < 5; i++) {
    const input = terminals.nth(i);
    const id = await input.getAttribute('value');
    check('hospitals cannot be final terminals', !id.startsWith('H-'));
    await input.setChecked(['D-NORTHPOINT', 'D-HOUGANG'].includes(id));
  }
  await postByClick('/api/dispatch/plan', limits.getByRole('button', { name: '应用并重新预览', exact: true }));
  const departure = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/depart'));
  const created = await postByClick('/api/dispatch/runs', page.getByRole('button', { name: '确认该计划并建立配送作业', exact: true }));
  const departed = await (await departure).json();
  const did = created.dispatch_id;
  check('confirmation creates and departs the live operation', departed.dispatch_id === did && departed.status === 'in_transit');
  await page.getByRole('button', { name: '⛶ 展开地图', exact: true }).click();
  await postByClick('/speed', page.locator('.tv-controls').getByRole('button', { name: '⏸ 暂停', exact: true }));
  await page.locator('.tv-close').click();
  const urgent = page.locator('.urgent-panel');
  check('urgent entry does not request cargo quantity', await urgent.locator('input[type=number]').count() === 0);
  await urgent.locator('.urgent-fields select').nth(2).selectOption('H-NUH');
  await urgent.getByLabel('最晚送达（当天）', { exact: true }).fill('17:00');
  const urgentPreview = await postByClick('/urgent-preview', urgent.getByRole('button', { name: '比较加急配送方案', exact: true }));
  const selected = urgentPreview.candidates.findIndex(c => c.feasible);
  check('an executable urgent candidate is available', selected >= 0);
  await urgent.locator(`input[name=urgent-candidate][value="${selected}"]`).check();
  const urgentAccepted = await postByClick('/urgent-accept', urgent.getByRole('button', { name: '采用选中方案并纳入作业', exact: true }));
  check('urgent stays in the existing operation', urgentAccepted.dispatch_id === did);
  await page.locator('header .header-plus').click();
  const modal = page.locator('.ni-body');
  await modal.locator('.ctl select').nth(0).selectOption(created.input.orders[0].order_id);
  await modal.locator('.ctl select').nth(1).selectOption('W-WESTGATE');
  for (const [index, value] of [[0, '20'], [1, '90'], [2, '19']]) {
    await modal.locator('.range-line input[type=number]').nth(index).fill(value);
  }
  const record = await postByClick('/api/case_close', page.getByRole('button', { name: '✓ 登记判定并归档', exact: true }));
  check('registered event links its original order and actual facility', record.event.dispatch_id === did && record.event.facility_id === 'W-WESTGATE');
  check('registered snapshot requires replacement', record.reshipment_required);
  const actions = page.locator('.case-actions');
  const replacement = await postByClick('/reshipments/preview', actions.getByRole('button', { name: '在此比较配送方案', exact: true }));
  const feasible = replacement.candidates.findIndex(c => c.feasible);
  check('quality replacement has an executable candidate', feasible >= 0);
  const reshipped = await postByClick('/api/dispatch/reshipments', actions.locator('.workflow-options tbody tr').nth(feasible).getByRole('button', { name: '采用此方案', exact: true }));
  check('replacement state and map share the original operation', reshipped.dispatch_id === did);
  await page.locator('.case-drawer-head .modal-x').click();
  // Register BEFORE resuming. The last tick can both complete the day and stop
  // polling; waiting only after the closing button appears misses that response.
  const completion = page.waitForResponse(async r => {
    if (!new URL(r.url()).pathname.endsWith('/tick') || !r.ok()) return false;
    const b = await r.json();
    return b.status === 'completed' && b.route_view.metrics.still_returning === 0;
  }, { timeout: 90000 });
  await postByClick('/speed', page.locator('.sg-ops').getByRole('button', { name: '300×', exact: true }));
  const endPreview = page.getByRole('button', { name: '预览今晚停车与次日固定计划', exact: true });
  await endPreview.waitFor({ state: 'visible', timeout: 90000 });
  const settled = await completion;
  const finalDay = await settled.json();
  check('actual ticks deliver the replacement', finalDay.orders[`RO-${record.run_id}`].status === 'delivered');
  await page.locator('.incident-card').filter({ hasText: '已处理' }).first().click();
  await page.locator('.workflow-note textarea').fill('Browser acceptance: replacement received and quality action reviewed');
  const closed = await postByClick(`/api/runs/${record.run_id}/workflow`, page.locator('.case-actions').getByRole('button', { name: '确认结案', exact: true }));
  check('incident closes only after actual delivery and operator remark', closed.processing_status === 'closed');
  await page.locator('.case-drawer-head .modal-x').click();
  await page.locator('.qline input').fill('audit chain');
  const qa = await postByClick('/api/qa', page.locator('.qline').getByRole('button', { name: '提问', exact: true }));
  check('browser QA reads the real case-specific graph evidence', qa.status === 'ok' && qa.evidence.some(e => e.node_id === record.run_id));
  const parking = await postByClick('/overnight-preview', endPreview);
  check('parking and next-day plan are feasible', parking.feasible);
  await postByClick('/overnight-accept', page.getByRole('button', { name: '确认并执行停车位移', exact: true }));
  const nextButton = page.getByRole('button', { name: /建立次日固定计划并发车/ });
  await nextButton.waitFor({ state: 'visible', timeout: 90000 });
  const tomorrow = await postByClick('/next-day', nextButton);
  check('next-day date increments independently of real date', tomorrow.operating_date === '2026-10-02');
  check('temporary urgent and replacement excluded from fixed next day', tomorrow.input.orders.length === 4 && tomorrow.input.orders.every(o => !o.source_run_id && !o.replaces_order_id));
  await page.getByRole('button', { name: '离线规则沙箱', exact: true }).click();
  check('offline sandbox contains no execution/registration actions', await page.locator('.case-actions').count() === 0);
  await page.locator('.case-drawer-head .modal-x').click();
  check('no uncaught Vue/browser exception', errors.length === 0);
  await page.screenshot({ path: `output/playwright/full-demo-${Date.now()}.png`, fullPage: true });
  return { status: 'passed', check_count: checks.length, checks, dispatch_id: did, next_dispatch_id: tomorrow.dispatch_id, run_id: record.run_id };
}
