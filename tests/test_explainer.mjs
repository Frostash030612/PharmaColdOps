import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {STORY,sceneAt,noteAt} from '../media/explainer/story.mjs';
import {drawFrame} from '../media/explainer/scene.mjs';
import {evaluate} from '../frontend-vue/src/lib/engine.js';
import en from '../frontend-vue/src/i18n/en.js';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');

test('nine contiguous English scenes cover exactly 90 seconds',()=>{
 assert.equal(STORY.scenes.length,9);assert.equal(STORY.scenes[0].start,0);assert.equal(STORY.scenes.at(-1).end,90);
 for(let i=0;i<9;i++){
   const s=STORY.scenes[i];assert.ok(s.end>s.start);if(i)assert.equal(s.start,STORY.scenes[i-1].end);
   for(const text of [s.title,s.tag,s.scope,...s.notes])assert.match(text,/^[\x20-\x7e]+$/);
   assert.equal(sceneAt(s.start).id,s.id);assert.ok(s.notes.includes(noteAt(s.start+.2)));
 }
 assert.equal(sceneAt(-1).id,'alarm');assert.equal(sceneAt(90).id,'close');
});
test('prototype values and illustrated rule are the actual implementation values',()=>{
 const product=JSON.parse(fs.readFileSync(path.join(root,'src/rule_engine/rules_config.json'))).products.find(p=>p.product_id===STORY.prototype.productId);
 assert.equal(product.storage_min_c,STORY.prototype.minC);assert.equal(product.storage_max_c,STORY.prototype.maxC);assert.equal(product.allowable_duration_min,STORY.prototype.allowableMin);
 const spec={min:product.storage_min_c,max:product.storage_max_c,allowable:product.allowable_duration_min,mktThreshold:product.mkt_threshold_c,retestable:product.retestable,freezeSensitive:product.freeze_sensitive};
 const event={product_id:product.product_id,excursion_temp_c:20,duration_min:90,mkt_c:20,packaging:'intact',stage:'transit'};
 const result=evaluate(event,spec,en);assert.equal(result.ruleNo,3);assert.equal(result.disposition,'scrap');
});
test('hot-window illustration has its stated duration and a constant 20 C temperature',()=>{
 const rows=STORY.observation.intervals.filter(row=>row[2]>STORY.prototype.maxC);
 assert.equal(rows.reduce((n,[a,b])=>n+b-a,0),STORY.observation.hotMin);
 assert.ok(rows.every(row=>row[2]===STORY.observation.hotMktC));
});
test('route comparison stays tied to the frozen reported same-fleet values',()=>{
 const doc=fs.readFileSync(path.join(root,'docs/M5正式评估.md'),'utf8');
 assert.match(doc,/\| Singapore \| 3\/165\.26 \| 3\/137\.85/);
 const b=STORY.routeBenchmark;assert.equal((100*(1-b.optimizedKm/b.greedyKm)).toFixed(2),'16.59');assert.equal(b.vehicles,3);assert.equal(b.solverRuns,49);
 assert.ok(STORY.scenes.find(s=>s.id==='benchmark').notes.join(' ').includes('not measured operating savings'));
});
test('parking counts and selected IDs are real warehouse choices, never hospitals',()=>{
 const network=JSON.parse(fs.readFileSync(path.join(root,'frontend-vue/src/data/singaporeRoutes.json'),'utf8'));
 assert.equal(network.nodes.filter(n=>n.role==='customer').length,STORY.parking.receivingHospitals);
 assert.equal(network.nodes.filter(n=>['depot','distribution','third_party'].includes(n.role)).length,STORY.parking.warehouseChoices);
 for(const id of STORY.parking.selected)assert.ok(network.nodes.some(n=>n.facility_id===id&&n.role==='distribution'));
});
test('illustration and evidence boundaries remain visible',()=>{
 assert.match(STORY.scenes.find(s=>s.id==='review').scope,/NOT AN ACTUAL HUMAN REVIEW/);
 assert.match(STORY.scenes.find(s=>s.id==='routes').scope,/NOT A SOLVER REPLAY OR GPS/);
 assert.match(STORY.scenes.find(s=>s.id==='close').scope,/NOT ESTABLISHED/);
 assert.match(STORY.scenes.find(s=>s.id==='evidence').notes.join(' '),/graph answers do not replace review history/);
 for(const source of STORY.sources)assert.ok(fs.existsSync(path.join(root,source)),source);
});

const modules=process.env.PHARMA_RENDER_MODULES;
test('native Canvas is deterministic, animated and keeps all sampled English text in frame',{skip:!modules},()=>{
 const require=createRequire(path.join(modules,'resolve.cjs'));
 const {createCanvas,GlobalFonts}=require('@napi-rs/canvas');
 for(const font of ['Arial.ttf','Arial Bold.ttf'])GlobalFonts.registerFromPath('/System/Library/Fonts/Supplemental/'+font,'Arial');
 const c=createCanvas(1920,1080),ctx=c.getContext('2d');const before=JSON.stringify(STORY);
 drawFrame(ctx,38);const a=c.toBuffer('image/png');drawFrame(ctx,38);assert.deepEqual(c.toBuffer('image/png'),a);
 drawFrame(ctx,32);assert.notDeepEqual(c.toBuffer('image/png'),a);
 for(const s of STORY.scenes)for(const t of [s.start+.1,s.start+.8,(s.start+s.end)/2,s.end-.1]){
   const frame=drawFrame(ctx,t,{diagnostics:true});
   assert.ok(frame.textBounds.every(b=>b.x>=55&&b.y>=15&&b.x+b.w<=1865&&b.y+b.h<=1078),JSON.stringify({t,frame}));
   assert.ok(frame.textBounds.every(b=>/^[\x20-\x7e]+$/.test(b.text)));
 }
 assert.equal(JSON.stringify(STORY),before);
});
test('full circular guards render in native Canvas, including the negative-angle workaround',{skip:!modules},()=>{
 const require=createRequire(path.join(modules,'resolve.cjs'));
 const {createCanvas}=require('@napi-rs/canvas');const c=createCanvas(1920,1080),ctx=c.getContext('2d');
 drawFrame(ctx,38);const pixel=ctx.getImageData(1034,481,2,2).data;assert.ok(pixel[1]>150,'human review circle must not disappear');
});
