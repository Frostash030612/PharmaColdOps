// Playwright CLI, isolated current-source API/Vue only. Never run on live data.
async(page)=>{
  await page.reload();
  const errors=[],requests=[];
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('request',r=>{if(new URL(r.url()).pathname==='/api/qa'&&r.method()==='POST')requests.push(r);});
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const api=new URL(page.url()).searchParams.get('api');
  assert(api&&new URL(api).hostname==='127.0.0.1'&&new URL(api).port!=='8080','isolated API required');
  const archive=await page.request.get(api+'/api/runs?limit=200').then(r=>r.json());
  const records=Array.isArray(archive)?archive:archive.runs;
  assert(records.length===2,'use fresh verification store with two prepared cases');
  const ids=records.map(r=>r.run_id);
  await page.setViewportSize({width:1600,height:1100});
  const qa=page.locator('.qa-query-kind').locator('..');
  const input=qa.locator('.qline input'),kind=qa.getByRole('combobox'),button=qa.getByRole('button',{name:'Ask',exact:true});
  const source=qa.locator('.qa-source'),answer=qa.locator('.answer');
  const initialAnswer=await answer.innerText();
  const clickQuery=async()=>{
    const [response]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/qa'),button.click()]);
    assert(response.ok(),`QA ${response.status()} ${await response.text()}`);return response.json();
  };
  const selectCase=async id=>{
    await page.locator('.hist-row').filter({hasText:id}).first().click();
    await page.locator('.case-drawer-head .modal-x').click();
    assert((await qa.locator('.qa-context').innerText()).includes(id),'wrong case scope');
  };
  for(const question of ['What will the weather be tomorrow?','Certify actual potency of this vaccine brand']){
    await input.fill(question);await button.click();
    assert((await source.innerText()).includes('Unsupported'),'out-of-scope question not refused');
    assert(requests.length===0,'refusal unnecessarily queried graph');
  }
  await input.fill('What is MKT?');await button.click();
  assert((await source.innerText()).includes('no graph query'),'concept masquerades as case evidence');
  await input.fill('Who approved the batch?');await button.click();
  assert((await source.innerText()).includes('Clarify'),'pronoun who matched WHO');
  assert(requests.length===0,'concept/clarification queried graph');

  await kind.selectOption('why_disposition');await input.fill('');await button.click();
  assert((await answer.innerText()).includes('archive a case'),'missing case not guarded');
  assert(requests.length===0,'missing case queried graph');
  await kind.selectOption('product_requirements');
  const product=await clickQuery();
  assert(product.answer.includes('engineering assumptions'),'unqualified product stability claim');
  assert(await qa.locator('.qa-evidence a').count()>0,'recorded source links missing');
  assert((await qa.locator('.qa-evidence a').first().getAttribute('href')).startsWith('https://'),'unsafe source protocol');
  await qa.screenshot({path:'output/playwright/m6-quality-20261017/qa-product.png'});
  const beforeMismatch=requests.length;
  await input.fill('Insulin storage requirements');await button.click();
  assert((await source.innerText()).includes('Clarify')&&requests.length===beforeMismatch,'named product silently changed query scope');
  await input.fill('');

  await selectCase(ids[0]);
  assert(await source.count()===0,'previous answer survived case switch');
  await kind.selectOption('why_disposition');
  const original=await clickQuery();
  assert(original.answer.includes(ids[0]),'answer is not case specific');
  let release,seen;
  const gate=new Promise(resolve=>release=resolve),fetched=new Promise(resolve=>seen=resolve);
  const delay=async route=>{const response=await route.fetch();seen();await gate;await route.fulfill({response});};
  await page.route('**/api/qa',delay);
  try{
    const completed=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/qa');
    await button.click();await fetched;
    await selectCase(ids[1]);
    release();const response=await completed;await response.finished();
    assert((await answer.innerText())===initialAnswer,'late old-case response was rendered');
    assert(await source.count()===0,'late response left old evidence/source badge');
  }finally{release();await page.unroute('**/api/qa',delay);}
  const fresh=await clickQuery();
  assert(fresh.answer.includes(ids[1])&&!fresh.answer.includes(ids[0]),'new case inherited previous facts');

  const abort=route=>route.abort('failed');await page.route('**/api/qa',abort);
  try{await button.click();await qa.getByText('Query unavailable / no graph result',{exact:true}).waitFor();
    assert((await answer.innerText()).includes('unavailable'),'transport failure became concept answer');
    assert(await qa.locator('.qa-evidence li').count()===0,'transport failure retained evidence');
  }finally{await page.unroute('**/api/qa',abort);}
  await kind.selectOption('product_requirements');await clickQuery();
  await qa.screenshot({path:'output/playwright/m6-quality-20261017/qa-final.png'});
  const after=await page.request.get(api+'/api/runs?limit=200').then(r=>r.json());
  assert(JSON.stringify(archive)===JSON.stringify(after),'read-only UI checks changed cases');
  assert(errors.length===0,JSON.stringify(errors));
  return{status:'passed',prepared_cases:2,refusal_and_concept_requests:0,source_links:true,
    no_case_guard:true,named_scope_guard:true,stale_response_cancelled:true,transport_failure_injected:true,
    case_response_unchanged:true,page_errors:errors};
}
