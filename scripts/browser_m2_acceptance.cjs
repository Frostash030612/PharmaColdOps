// Playwright CLI run-code --filename on a fresh isolated API page, new-case modal open.
// Uses visible UI only for generation, analysis, selection and registration.
async (page) => {
  const errors = []; page.on('pageerror', e => errors.push(String(e)));
  const panel = page.locator('.ni-body .m2-panel');
  const archive = page.getByRole('button', { name: '✓ 登记判定并归档', exact: true });
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const responseClick = async (suffix, button) => {
    const [r] = await Promise.all([page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === suffix), button.click()]);
    assert(r.ok(), `${suffix}: ${r.status()} ${await r.text()}`); return r.json();
  };
  await panel.getByRole('button', { name: '序列计算', exact: true }).click();
  const generate = async scenario => {
    await panel.getByRole('combobox', { name: '模拟场景', exact: true }).selectOption(scenario);
    return responseClick('/api/m2/simulate', panel.getByRole('button', { name: '生成并分析', exact: true }));
  };
  const normal = await generate('normal');
  assert(normal.analysis.windows.length === 0 && await archive.isDisabled(), 'normal created phantom excursion');
  const missing = await generate('gap');
  assert(!missing.analysis.coverage_complete && await archive.isDisabled(), 'missing data allowed registration');
  assert(await panel.getByRole('button', { name: '选用此窗口，登记为待审核', exact: true }).count() > 0, 'missing data has no human-review entry');
  const mixed = await generate('mixed');
  assert(mixed.analysis.windows.length === 2 && mixed.analysis.windows[1].kind === 'cold', 'cold excursion lost');
  await page.locator('.ni-body .controls select').nth(2).selectOption('H-SGH');
  await panel.getByRole('button', { name: '选用此窗口登记', exact: true }).first().click();
  assert(await archive.isEnabled(), 'selected complete window not usable');
  for (const input of await page.locator('.ni-body .range-line input').all()) assert(await input.isDisabled(), 'derived scalar editable');
  await panel.getByLabel('随机种子', { exact: true }).fill('43');
  assert(await archive.isDisabled() && await panel.locator('.m2-window').count() === 0, 'stale analysis survived edit');
  await panel.locator('summary').click();
  await panel.getByLabel('温度区间 JSON', { exact: true }).fill(JSON.stringify([
    { start_min: 0, end_min: 20, temp_c: 5 }, { start_min: 20, end_min: 30.5, temp_c: 12 },
    { start_min: 30.5, end_min: 120, temp_c: 5 },
  ]));
  const analysis = await responseClick('/api/m2/analyse', panel.getByRole('button', { name: '分析编辑后的序列', exact: true }));
  assert(analysis.windows[0].event.duration_min === 11 && Math.abs(analysis.windows[0].event.mkt_c - 12) < 1e-8, 'fractional interval calculation incorrect');
  await panel.getByRole('button', { name: '选用此窗口登记', exact: true }).click();
  let committed;
  const lostResponse = async route => {
    const actual = await route.fetch();
    assert(actual.ok(), `registration refused: ${await actual.text()}`);
    committed = await actual.json();
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'M2 acceptance: response lost after commit' }) });
  };
  await page.route('**/api/case_close', lostResponse);
  await archive.click();
  await page.getByRole('button', { name: '重试本次登记', exact: true }).waitFor();
  await page.unroute('**/api/case_close', lostResponse);
  assert(committed?.temperature_assessment?.source_hash === analysis.source_hash, 'first registration did not persist source');
  await page.reload();
  await page.getByRole('button', { name: '+', exact: true }).click();
  await page.locator('.ni-body .m2-panel').getByText(/重试草稿已冻结/).waitFor();
  const record = await responseClick('/api/case_close', page.getByRole('button', { name: '重试本次登记', exact: true }));
  assert(record.run_id === committed.run_id, 'retry created duplicate temperature case');
  assert(record.temperature_context.series.source === 'manual_simulated' && record.temperature_assessment.source_hash === analysis.source_hash, 'source snapshot missing');
  assert(record.event.duration_min === 11 && record.disposition === 'scrap', 'M3 did not receive calculated event');
  const saved = page.locator('.case-drawer .m2-panel');
  await saved.getByText(analysis.source_hash, { exact: false }).waitFor();
  assert(await saved.locator('.m2-chart line').count() === 3 && await saved.getByRole('button').count() === 0, 'archive did not render immutable original intervals');
  await page.setViewportSize({ width: 1366, height: 1000 });
  await saved.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `output/playwright/m2-panel-${Date.now()}.png` });
  await page.screenshot({ path: `output/playwright/m2-archive-${Date.now()}.png`, fullPage: true });
  await page.locator('.case-drawer-head .modal-x').click();
  await page.reload();
  await page.locator('.incident-card').first().click();
  await page.locator('.case-drawer .m2-panel').getByText(analysis.source_hash, { exact: false }).waitFor();
  await page.locator('.case-drawer-head .modal-x').click();
  await page.getByRole('button', { name: 'EN', exact: true }).click();
  await page.locator('.incident-card').first().click();
  assert((await page.locator('.case-drawer .m2-panel').innerText()).includes('Temperature series and excursions'), 'English M2 missing');
  await page.locator('.case-drawer-head .modal-x').click();
  await page.getByRole('button', { name: '中文', exact: true }).click();
  let requests = 0;
  const observe = r => { if (r.url().includes('/api/m2/')) requests++; }; page.on('request', observe);
  await page.getByRole('button', { name: '离线规则沙箱', exact: true }).click();
  await page.locator('.case-drawer .timeline-source-note').waitFor();
  await page.locator('.case-drawer-head .modal-x').click();
  page.off('request', observe);
  assert(requests === 0 && errors.length === 0, `offline requests=${requests}; page errors=${errors}`);
  return { status: 'passed', run_id: record.run_id, source_hash: analysis.source_hash,
    duration_exact_min: 10.5, duration_min: record.event.duration_min, mkt_c: record.event.mkt_c,
    disposition: record.disposition, normal_windows: normal.analysis.windows.length,
    gap_coverage: missing.analysis.coverage_ratio, mixed_windows: mixed.analysis.windows.length,
    recovered_retry_same_run: record.run_id === committed.run_id, offline_m2_requests: requests, errors };
}
