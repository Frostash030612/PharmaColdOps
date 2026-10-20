/* New final briefing deck. Original proposal decks are never overwritten.
   Use the bundled artifact runtime, not repository-local presentation packages. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL,fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const args={};
for(let i=2;i<process.argv.length;i++){
  if(process.argv[i]==='--help'){
    console.log('Required: --build-dir NEW_DIRECTORY --output NEW.pptx --runtime-modules PATH --runtime-python PATH --skill-dir PATH. Optional: --qa-screenshot PATH --verification PATH --m6-report PATH.');
    process.exit(0);
  }
  const key=process.argv[i];if(!key.startsWith('--')||!process.argv[i+1])throw Error('invalid argument');
  args[key.slice(2)]=process.argv[++i];
}
for(const key of ['build-dir','output','runtime-modules','runtime-python','skill-dir'])if(!args[key])throw Error('missing --'+key);
const build=path.resolve(args['build-dir']),output=path.resolve(args.output),skill=path.resolve(args['skill-dir']);
// The first-party import validator runs in a child Node process.
process.env.RUNTIME_NODE_MODULES=path.resolve(args['runtime-modules']);
if(!output.startsWith(root+path.sep)||!build.startsWith(root+path.sep))throw Error('build/output must be inside the task workspace');
for(const name of [build,output]){try{await fs.access(name);throw Error('fresh build/output required: '+name);}catch(e){if(e.code!=='ENOENT')throw e;}}
await fs.mkdir(build,{recursive:true});await fs.mkdir(path.dirname(output),{recursive:true});
await fs.symlink(path.resolve(args['runtime-modules']),path.join(build,'node_modules'),'dir');
const require=createRequire(path.join(build,'resolve.cjs'));
const {Presentation,PresentationFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const {finalizePresentation,resolvePresentationFont,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const font=resolvePresentationFont({fontFamily:'Arial'});
const ink='#063E5F',gold='#B88E23',muted='#536272',paper='#FFFDFA';
const p=Presentation.create({slideSize:{width:1280,height:720}});
const evidence={regression:'Previous full regression: 909 tests',workflow:'36 API workflow checks'};
if(args.verification){
  const v=JSON.parse(await fs.readFile(args.verification,'utf8'));
  if(v.status!=='passed'||!v.pytest?.length||v.pytest.some(s=>Number(s.failures)||Number(s.errors)||Number(s.skipped)))throw Error('verification is incomplete');
  evidence.regression=`Full regression: ${v.pytest.reduce((n,s)=>n+Number(s.tests),0)} passed, no skips`;
  if(v.demo?.check_count)evidence.workflow=`${v.demo.check_count} API workflow checks`;
}
let human=null;
if(args['m6-report']){
  human=JSON.parse(await fs.readFile(args['m6-report'],'utf8'));
  if(human.schema!=='m6-independent-human-evaluation-v1'||human.status!=='scored_on_supplied_human_annotations'||!human.process_record_sha256||human.process_declarations_self_reported!==true)throw Error('use a process-validated finalize_m6_review report');
  for(const k of ['intent_accuracy','independent_answer_adequacy_rate_both_raters'])if(typeof human[k]!=='number'||human[k]<0||human[k]>1)throw Error('invalid human metric');
}
function text(slide,value,x,y,w,h,size=28,color=ink,bold=false){
  const shape=slide.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  shape.text=value;shape.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none',wrap:'square',insets:0};
  return shape;
}
function slide(title,source,notes){
  const s=p.slides.add();s.background.fill=paper;
  text(s,title,60,40,1160,75,44,ink,true);
  const captions={
    'System workflow':'Group report, implemented architecture and workflow',
    'Rule evaluation':'M3 formal report, frozen synthetic scenarios',
    'Risk and candidate-cause models':'M4 formal report, outer five-fold experiments',
    'Temporal event study':'Event-v2 report, same five held-out simulated cohorts',
    'Static route comparison':'M5 formal report, frozen Singapore static instance',
    'Delivery execution constraints':'Execution acceptance and warehouse parking contracts',
    'M6 question-answering repairs':'Observed review failures and developer software checks',
    'Verification and human review':'Release verification and frozen human-review records',
    'Limitations and delivery':'Course requirements and final delivery checklist',
  };
  text(s,captions[title]||source,60,668,1110,34,16,muted);
  text(s,String(p.slides.items.length).padStart(2,'0'),1180,668,50,30,17,gold);
  s.speakerNotes.text=notes+'\nSources: '+source+'\nData are simulated. Metrics retain their original dataset, split and denominator. Human presentation only.';
  return s;
}
function lines(s,items,{x=60,y=155,w=1160,size=29,step=91}={}){
  items.forEach((value,i)=>text(s,value,x,y+i*step,w,step-12,size));
}
function table(s,values,{x=60,y=166,w=1160,h=365,widths}={}){
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,columnWidths:widths});
  t.borders.assign({style:'solid',fill:'#D9D9D9',width:1});
  for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){
    const cell=t.getCell(r,c);cell.fill=r===0?ink:(r%2?'#F1F4F6':paper);
    cell.text.style={typeface:font,fontSize:r===0?25:26,color:r===0?'#FFFFFF':ink,bold:r===0,autoFit:'none',wrap:'square',insets:12};
  }
  return t;
}
async function image(s,file,x,y,w,h,alt){
  const data=await fs.readFile(path.resolve(root,file));
  s.images.add({blob:data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength),contentType:'image/png',alt,fit:'contain',position:{left:x,top:y,width:w,height:h}});
}

{
  const s=p.slides.add();s.background.fill=ink;
  text(s,'PharmaColdOps',70,135,1140,100,68,'#FFFFFF',true);
  text(s,'Cold-chain decisions and delivery replanning',70,260,1100,100,36,'#FFFFFF');
  text(s,'Project Group 41',70,450,1100,55,30,'#FFFFFF');
  text(s,'Final briefing  17 October 2026',70,520,1100,45,25,'#FFFFFF');
  text(s,'Simulated data. Human review governs consequential actions.',70,634,1100,45,22,'#FFFFFF');
  s.speakerNotes.text='D, 20 seconds. Introduce the business problem and disclose simulated inputs. The team should write and speak its own final wording. Do not claim real hospital deployment or clinical validation. Sources: docs/FINAL_REPORT_EN.md, member-github.txt.';
}
{
  const s=slide('System workflow','docs/FINAL_REPORT_EN.md, sections 3–4','A, 35 seconds. Explain the event, rule, human review, dispatch and case-evidence path. M4 stays advisory. Describe why raw records and human outcomes remain separate.');
  await image(s,'docs/figures/final-system-architecture.png',80,135,1120,450,'Implemented seven-module system architecture');
  text(s,'Recorded evidence and effective human decisions remain separate',60,600,1160,50,27);
}
{
  const s=slide('Rule evaluation','docs/M3正式评估.md, historical rubric v1.1','A, 30 seconds. State 54/57 historical agreement and expose the quarantine failures. Distinguish engine-to-gold kappa 0.9097 from human-human kappa 0.6434. The review workflow protects execution but does not change frozen automatic predictions.');
  table(s,[['Historical label','Support','Recall','F1'],['release','13','1.0000','0.9286'],['retest','8','1.0000','0.9412'],['quarantine','3','0.0000','0.0000'],['scrap','33','1.0000','1.0000']],{widths:[365,200,285,310],h:355});
  text(s,'54/57 agreement. Macro-F1 0.7174. Quarantine recall 0/3.',60,548,1160,55,29);
  text(s,'Synthetic historical scenarios, with known policy disagreements',60,610,1160,40,23,muted);
}
{
  const s=slide('Risk and candidate-cause models','docs/M4正式实验.md, formal outer folds','B, 40 seconds. Risk and causes are separate prediction tasks. Explain calibration and why monthly cause classification remains weak. There are no brand-specific potency labels or verified causal diagnoses.');
  table(s,[['Shipment-risk measure','Five-fold result'],['F1','0.6635 +/- 0.0179'],['ROC-AUC','0.9045 +/- 0.0092'],['PR-AUC','0.7087 +/- 0.0296'],['Brier, raw to calibrated','0.1091 to 0.0933']],{widths:[570,590],h:345});
  text(s,'Monthly causes: macro-F1 0.1322, Top-1 0.1713',60,545,1160,55,29);
  text(s,'Random-fold full15 results. Candidate associations require review.',60,605,1160,45,23,muted);
}
{
  const s=slide('Temporal event study','docs/事件时序模型v2评估.md, five held-out roles','B, 35 seconds. Compare models on the same frozen simulated test cohorts. Explain missing multi-fault mechanisms, uncalibrated scores and screening coverage. Extreme screening supports zero events, and all results require human review.');
  text(s,'Macro-F1 (0–1)',80,125,1110,35,23,muted);
  const chart=s.charts.add('bar',{position:{left:80,top:160,width:1110,height:370},categories:['Nominal assets','Other assets','New excitation','Covered stress','Extreme stress'],
    series:[{name:'Earlier event model',values:[.6125,.6111,.5880,.5126,.5068],fill:'#B9C2CB'},
            {name:'Temporal v2',values:[.7668,.7619,.7228,.7528,.6505],fill:gold}],
    barOptions:{direction:'column',grouping:'clustered'},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:22}},
    yAxis:{min:0,max:1,numberFormatCode:'0.0',textStyle:{fontSize:21}},xAxis:{textStyle:{fontSize:20}},
    dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.00',textStyle:{fontSize:19}}});
  applyPresentationChartFont(chart,{fontFamily:font});
  text(s,'Supported coverage: 17.33%, 20.67%, 13.83%, 2.50%, 0%',60,553,1160,50,27);
  text(s,'Same simulator. All 3,000 test events still require human review.',60,610,1160,45,24,muted);
}
{
  const s=slide('Static route comparison','docs/M5正式评估.md, frozen Singapore instance','C, 35 seconds. Both plans use three vehicles. The distance reduction is 16.59% for one frozen static instance, not a measured operational saving. Explain the fleet-first objective and why different-fleet BKS distances are incomparable.');
  text(s,'Total distance (km)',130,125,1010,35,23,muted);
  const chart=s.charts.add('bar',{position:{left:130,top:160,width:1010,height:365},categories:['Greedy','OR-Tools GLS'],
    series:[{name:'Distance (km)',values:[165.26,137.85],fill:ink}],hasLegend:false,
    barOptions:{direction:'column',grouping:'clustered',gapWidth:180},
    yAxis:{min:0,max:180,numberFormatCode:'0',textStyle:{fontSize:22}},xAxis:{textStyle:{fontSize:26}},
    dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.00',textStyle:{fontSize:26}}});
  applyPresentationChartFont(chart,{fontFamily:font});
  text(s,'3 vehicles in each plan. 49 static comparisons overall.',60,555,1160,50,29);
  text(s,'Complete feasibility comes before fleet size and distance.',60,615,1160,40,24,muted);
}
{
  const s=slide('Delivery execution constraints','docs/完整演示与端到端验收.md; docs/独立加急与仓库停车规则.md','C, 25 seconds. Distinguish route previews, adopted plans and actual simulated delivery state. Explain the five-warehouse parking restriction and that hospitals cannot be final terminals. Do not invent vehicle-to-vehicle transfer.');
  lines(s,['Explicit adoption changes the operation','Urgent orders share the current delivery operation','Delay and failure handling retain completed work','Day-end terminals are selected warehouses only','Orders, progress and available resources are simulated'],{step:88,size:29});
}
{
  const s=slide('M6 question-answering repairs','docs/M6问答修复与新版本验收.md; reviewer A observations','D, 35 seconds. Describe exact scope: deterministic routing, five explicit structured queries, labelled concepts, refusal outside scope, reference links and stale-response cancellation. The old frozen review remains unchanged. Regression checks do not establish new independent accuracy.');
  lines(s,['Explicit query types and visible case scope','Unsupported questions receive a refusal','Concepts do not become case evidence','Reference links preserve recorded provenance'],{x:60,y:165,w:560,size:27,step:98});
  await image(s,args['qa-screenshot']||'docs/figures/m6-qa-current-en.png',650,150,555,425,'Current local QA controls, product assumptions and graph-query source badge');
  text(s,'Frozen review results remain distinct from repaired-system quality',60,600,1160,50,25,muted);
}
{
  const s=slide('Verification and human review','PROGRESS.md; process-validated M6 report when supplied','D, 25 seconds. State the software verification evidence. If B is missing, say so. Human process declarations are not identity authentication. Do not substitute developer-authored checks for an independent benchmark.');
  lines(s,[evidence.regression,evidence.workflow,'Persistence, graph recovery and read-only advisory checks',human?
    `Frozen M6 intent accuracy ${human.intent_accuracy.toFixed(4)}, both-rater adequacy ${human.independent_answer_adequacy_rate_both_raters.toFixed(4)}`:
    'M6: reviewer B and process evidence remain pending'],{step:105,size:29});
  text(s,'Current-router independent accuracy is not established',60,610,1160,40,24,muted);
}
{
  const s=slide('Limitations and delivery','docs/最终交付与验收.md','D, 20 seconds. Close with supported capabilities and honest limits. Remaining human items include B review/provenance, recordings, individual reflection and confidential peer evaluation. Original proposal slides are historical, and the current group is 41.');
  lines(s,['Engineering thresholds require product-level evidence','Model candidates cannot authorise medicine disposition','The local prototype has no public-user authentication','Human recordings, review and individual reports remain team tasks'],{step:108,size:29});
  text(s,'Runnable prototype, inspectable evidence and reproducible experiments',60,614,1160,38,25,gold);
}

for(let i=0;i<p.slides.items.length;i++){
  const slide=p.slides.items[i];
  const blob=await p.export({slide,format:'png',scale:1});
  await fs.writeFile(path.join(build,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
}
const candidate=path.join(build,'candidate.pptx');
await(await PresentationFile.exportPptx(p)).save(candidate);
await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:output,
  pythonExecutable:path.resolve(args['runtime-python']),
  integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--require-native-table-slide','3','--require-native-table-slide','4'],
  requiredNativeTableOwnerSlides:[3,4],requiredNativeChartOwnerSlides:[5,6],
  materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[font]},
  verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
await fs.writeFile(path.join(build,'facts.json'),JSON.stringify({slide_count:p.slides.items.length,verification:evidence,human_status:human?'supplied frozen-v1 review':'pending',scope:'no independent repaired-router accuracy claim'},null,2));
console.log(JSON.stringify({status:'exported_for_visual_review',slides:p.slides.items.length,output}));
