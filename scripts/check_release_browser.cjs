/* Dev-only real browser acceptance. No production dependency or remote writes.
 * npm install --no-save playwright-core; use installed Chrome via --chrome.
 * Set GASOPS_PLAYWRIGHT_MODULE to an isolated playwright-core installation.
 */
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.GASOPS_PLAYWRIGHT_MODULE||'playwright-core');
const args=Object.fromEntries(process.argv.slice(2).reduce((a,v,i,all)=>i%2?a:[...a,[v.slice(2),all[i+1]]],[]));
const base=(args.url||'http://127.0.0.1:8770').replace(/\/$/,'');
const output=path.resolve(args.output||'/tmp/igor-release-browser');
const report={url:base,routes:[],checks:[],blocked:0,errors:[]};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const chooseRadio=(page,name)=>page.getByRole('radio',{name,exact:true}).locator('xpath=ancestor::label[1]').click();

async function mapTarget(page,kind){
 return page.evaluate(kind=>{
  const canvas=document.querySelector('[data-testid="stDeckGlJsonChart"] canvas');
  let fiber=canvas[Object.keys(canvas).find(k=>k.startsWith('__reactFiber'))],deck;
  for(let i=0;fiber&&i<35;i++,fiber=fiber.return){
   if(fiber.stateNode?.deck)deck=fiber.stateNode.deck;
   for(let h=fiber.memoizedState,j=0;h&&j<20;j++,h=h.next)if(h.memoizedState?.current?.deck)deck=h.memoizedState.current.deck;
  }
  if(!deck)throw Error('Native Deck instance unavailable');
  const box=canvas.getBoundingClientRect(),viewport=deck.getViewports()[0];
  const layers=deck.layerManager.getLayers();
  if(kind==='point'){
   const point=layers.find(l=>l.id==='infrastructure-points').props.data.find(r=>r.infra_id==='it-lng-piombino');
   const p=viewport.project(point.position);
   return{x:box.x+p[0]-12,y:box.y+p[1],offset:12};
  }
  const layer=layers.find(l=>l.id==='pipeline-hit-targets');
  const features=layer.props.data.features;
  const points=layers.find(l=>l.id==='infrastructure-points').props.data.filter(r=>r.active!==false).map(r=>viewport.project(r.position));
  for(const feature of features){
   const paths=feature.geometry.type==='LineString'?[feature.geometry.coordinates]:feature.geometry.coordinates;
   for(const line of paths)for(let i=1;i<line.length;i++){
    const a=viewport.project(line[i-1]),b=viewport.project(line[i]),dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
    if(length<35)continue;
    const x=(a[0]+b[0])/2-8*dy/length,y=(a[1]+b[1])/2+8*dx/length;
    if(x>15&&y>15&&x<box.width-15&&y<box.height-15&&points.every(p=>Math.hypot(x-p[0],y-p[1])>18))return{x:box.x+x,y:box.y+y,offset:8};
   }
  }
  throw Error('No isolated pipeline test location');
 },kind);
}

function fixturePdf(){
  // One canary page; no real or confidential document enters the browser test.
  const content='BT /F1 12 Tf 40 700 Td (SESSION_A_CANARY public test document) Tj ET';
  const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',`<< /Length ${content.length} >>\nstream\n${content}\nendstream`];
  let text='%PDF-1.4\n',offsets=[0];
  objects.forEach((o,i)=>{offsets.push(Buffer.byteLength(text));text+=`${i+1} 0 obj\n${o}\nendobj\n`;});
  const xref=Buffer.byteLength(text);
  text+='xref\n0 6\n0000000000 65535 f \n'+offsets.slice(1).map(n=>String(n).padStart(10,'0')+' 00000 n \n').join('');
  return Buffer.from(text+`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
}

async function main(){
 await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({executablePath:args.chrome,headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--disk-cache-size=1']});
 try{
  async function newPage(width=1440,height=1000){
   const context=await browser.newContext({viewport:{width,height}});
   await context.route('**/*',route=>{
    if([base,args['workbench-url'],args['private-url']].filter(Boolean).some(u=>route.request().url().startsWith(u)))return route.continue();
    report.blocked++;return route.abort();
   });
   const page=await context.newPage();
   page.on('pageerror',e=>report.errors.push(e.name));
   page.setDefaultTimeout(45000);
   return page;
  }
  async function open(page,route,title,origin=base){
   const start=Date.now();
   await page.bringToFront();
   await page.goto(origin+'/'+route,{waitUntil:'domcontentloaded'});
   await page.getByRole('heading',{name:title,exact:true}).first().waitFor();
   await page.waitForFunction(()=>document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning');
   await delay(500);
   assert.equal(await page.getByTestId('stException').count(),0,route+' application error');
   report.routes.push({route:route||'/',origin,status:'PASS',milliseconds:Date.now()-start});
   console.log((route||'/')+': PASS');
  }
  const a=await newPage(),b=await newPage();
  await open(a,'','I.G.O.R. — Sistema Gas Italiano');
  await a.locator('[data-testid="stDeckGlJsonChart"] canvas').waitFor();
  await a.locator('[data-testid="stDeckGlJsonChart"] canvas').scrollIntoViewIfNeeded();
  await delay(400);
  let target=await mapTarget(a,'point');
  await a.mouse.move(target.x,target.y);
  await delay(500);
  await a.mouse.click(target.x,target.y,{delay:80});
  await delay(1000);
  await a.locator('.st-key-network_home_detail h3').filter({hasText:'Piombino'}).waitFor();
  report.checks.push({check:'native_marker_click_12px_offset',status:'PASS'});
  await a.screenshot({path:path.join(output,'overview-desktop.png'),fullPage:true});
  await a.waitForFunction(()=>document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning');
  await a.locator('[data-testid="stDeckGlJsonChart"] canvas').scrollIntoViewIfNeeded();
  await delay(500);
  target=await mapTarget(a,'pipeline');
  await a.mouse.move(target.x,target.y);
  await delay(400);
  assert((await a.locator('.deck-tooltip').allTextContents()).some(text=>text.includes('Gasdotti')),'Native pipeline hover must match the target');
  await a.mouse.click(target.x,target.y,{delay:80});
  await a.getByText('Collegamento storico schematico · nessuna misura di flusso sul segmento',{exact:true}).waitFor();
  report.checks.push({check:'native_pipeline_click_8px_offset',status:'PASS'});
  assert.equal(await a.locator('.st-key-net_mode_overview [role="radiogroup"] label').count(),3);
  await chooseRadio(a,'Flussi');
  await a.getByRole('radio',{name:'Flussi',exact:true}).press('ArrowRight');
  await a.getByRole('radio',{name:'Attenzione',exact:true}).waitFor();
  assert(await a.getByRole('radio',{name:'Attenzione',exact:true}).isChecked());
  await open(b,'','I.G.O.R. — Sistema Gas Italiano');
  assert(await b.getByRole('radio',{name:'Sistema',exact:true}).isChecked());
  report.checks.push({check:'independent_map_modes_and_keyboard',status:'PASS'});
  await a.bringToFront();
  await chooseRadio(a,'Sistema');
  await a.getByRole('button',{name:'Esplora la rete',exact:true}).click();
  await a.waitForURL('**/security-of-supply');
  await a.locator('[data-testid="stDeckGlJsonChart"] canvas').waitFor();
  report.checks.push({check:'overview_to_network',status:'PASS'});
  await chooseRadio(a,'Esplora dati');
  await a.getByRole('heading',{name:'Gas Data Explorer',exact:true}).waitFor();
  assert.equal(await a.getByTestId('stException').count(),0);
  report.checks.push({check:'data_explorer',status:'PASS'});
  if(args['no-provider-keys']==='true'){
   await chooseRadio(a,'Scorte');
   await a.getByText(/Accesso GIE non configurato/).waitFor();
   assert.equal(await a.getByTestId('stException').count(),0);
   report.checks.push({check:'missing_gie_credentials',status:'PASS'});
  }
  const routes=[['market','Mercato e previsioni'],['balancing','Bilanciamento'],['ledger','Fatture e garanzie'],
    ['risk','Simulazione rischi'],['operations','Assistente AI'],['kpi','Operazioni gas'],['connections','Fonti e API'],['demo','BSO, in sintesi']];
  for(const [route,title] of routes)await open(a,route,title);
  await open(a,'regulatory','Norme e documenti');
  await a.locator('input[type=file]').setInputFiles({name:'SESSION_A_CANARY.pdf',mimeType:'application/pdf',buffer:fixturePdf()});
  await a.getByRole('button',{name:'Aggiungi ai miei PDF',exact:true}).click();
  await a.getByText(/^1 PDF ·/).first().waitFor();
  assert(await a.getByRole('radio',{name:'I miei PDF',exact:true}).isChecked());
  await open(b,'regulatory','Norme e documenti');
  await chooseRadio(b,'I miei PDF');
  await delay(300);
  assert.equal(await b.getByText('SESSION_A_CANARY.pdf',{exact:true}).count(),0);
  assert(await b.getByText(/^0 PDF ·/).first().isVisible());
  report.checks.push({check:'two_browser_document_sessions',status:'PASS'});
  await a.screenshot({path:path.join(output,'documents-session-a.png'),fullPage:true});
  await b.screenshot({path:path.join(output,'documents-session-b.png'),fullPage:true});
  // Native report actions, with the unchanged fast seasonal reference model.
  await open(a,'operations','Assistente AI');
  await a.getByRole('button',{name:'Opzioni',exact:true}).click();
  await a.getByRole('combobox',{name:'Modello previsionale',exact:true}).click();
  await a.getByRole('option',{name:'Riferimento stagionale',exact:true}).click();
  await a.keyboard.press('Escape');
  await a.getByRole('button',{name:'Stress +10%',exact:true}).click();
  await a.getByText(/^Storico della sessione ·/).first().click();
  await a.getByRole('button',{name:'Svuota storico dell’assistente',exact:true}).waitFor();
  await open(b,'operations','Assistente AI');
  assert.equal(await b.getByRole('button',{name:'Svuota storico dell’assistente',exact:true}).count(),0);
  report.checks.push({check:'two_browser_reports_and_chat_sessions',status:'PASS'});
  await open(a,'market','Mercato e previsioni');
  await a.getByRole('button',{name:'Opzioni',exact:true}).click();
  await a.getByRole('combobox',{name:'Modello previsionale',exact:true}).click();
  await a.getByRole('option',{name:'Riferimento stagionale',exact:true}).click();
  await a.keyboard.press('Escape');
  await a.getByRole('button',{name:'Calcola previsione',exact:true}).click();
  await a.getByRole('button',{name:'Calcola previsione',exact:true}).waitFor({state:'hidden'});
  await a.waitForFunction(()=>document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning');
  assert.equal(await a.getByRole('button',{name:'Calcola previsione',exact:true}).count(),0);
  assert.equal(await a.getByTestId('stException').count(),0);
  await a.screenshot({path:path.join(output,'market-desktop.png'),fullPage:true});
  report.checks.push({check:'explicit_market_forecast',status:'PASS'});
  await open(a,'','I.G.O.R. — Sistema Gas Italiano');
  await a.getByRole('button',{name:'Esplora la rettifica',exact:true}).click();
  await a.waitForURL('**/demo');
  assert(await a.getByRole('radio',{name:'Rettifiche',exact:true}).isChecked());
  report.checks.push({check:'example_card_opens_exact_case',status:'PASS'});
  const mobile=await newPage(390,844);
  await open(mobile,'','I.G.O.R. — Sistema Gas Italiano');
  await mobile.locator('[data-testid="stDeckGlJsonChart"] canvas').waitFor();
  assert(await mobile.evaluate(()=>document.body.scrollWidth<=innerWidth));
  await mobile.screenshot({path:path.join(output,'overview-mobile.png'),fullPage:true});
  report.checks.push({check:'mobile_no_overflow',status:'PASS'});
  const operationalControls=mobile.locator('.st-key-network_camera_overview button, .st-key-system_day_nav button');
  assert.equal(await operationalControls.count(),5);
  const controlRects=await operationalControls.evaluateAll(nodes=>nodes.map(e=>{
   const r=e.getBoundingClientRect();return {height:r.height,width:r.width,top:r.top,bottom:r.bottom,left:r.left,right:r.right};
  }));
  assert(controlRects.every(r=>r.height>=43.5 && r.width>=44),'Operational controls must have generous targets');
  const mapBottom=await mobile.locator('[data-testid="stDeckGlJsonChart"]').evaluate(e=>e.getBoundingClientRect().bottom);
  const cameraRects=await mobile.locator('.st-key-network_camera_overview button').evaluateAll(nodes=>nodes.map(e=>e.getBoundingClientRect().top));
  assert(cameraRects.every(top=>top>=mapBottom-1),'Camera controls must not obscure the map');
  for(let i=0;i<controlRects.length;i++)for(let j=i+1;j<controlRects.length;j++){
   const a=controlRects[i],b=controlRects[j];
   assert(a.right<=b.left || b.right<=a.left || a.bottom<=b.top || b.bottom<=a.top,'Controls must not overlap');
  }
  report.checks.push({check:'mobile_operational_controls_targets_and_no_overlap',status:'PASS'});
  await open(mobile,'market','Mercato e previsioni');
  assert(await mobile.evaluate(()=>document.body.scrollWidth<=innerWidth));
  const targets=await mobile.locator('[class*="st-key-workspace_nav_"] [role="radiogroup"] label').evaluateAll(labels=>labels.map(e=>e.getBoundingClientRect().height));
  assert(targets.length>=10 && targets.every(h=>h>=44));
  await mobile.screenshot({path:path.join(output,'market-mobile.png'),fullPage:true});
  report.checks.push({check:'mobile_workspace_targets_and_reflow',status:'PASS'});
  if(args['workbench-url']){
   const workbench=await newPage();
   await open(workbench,'','I.G.O.R. — Sistema Gas Italiano',args['workbench-url']);
   await workbench.locator('[data-testid="stDeckGlJsonChart"] canvas').waitFor();
   report.checks.push({check:'workbench_overview',status:'PASS'});
  }
  if(args['private-url']){
   const unauthorized=await newPage();
   for(const route of ['','operations?profile=public_demo&authenticated=true','regulatory']){
    await open(unauthorized,route,'Accesso riservato',args['private-url']);
    assert.equal(await unauthorized.locator('input[type=file]').count(),0);
   }
   report.checks.push({check:'private_direct_urls_denied',status:'PASS'});
  }
  assert.equal(report.errors.length,0);
 }finally{
  await browser.close();
  await fs.writeFile(path.join(output,'acceptance.json'),JSON.stringify(report,null,2)+'\n');
 }
}
main().catch(async error=>{report.failure=error.message;await fs.mkdir(output,{recursive:true});await fs.writeFile(path.join(output,'acceptance.json'),JSON.stringify(report,null,2)+'\n');process.exitCode=1;console.error(error.message);});
