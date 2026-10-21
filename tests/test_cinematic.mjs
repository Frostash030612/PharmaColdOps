import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {FILM,shotAt,noteAt,ease} from '../media/cinematic/story.mjs';

test('the six scenes exactly preserve the supplied 2:30 storyboard',()=>{
 assert.equal(FILM.duration,150);assert.equal(FILM.language,'en');assert.equal(FILM.fps,30);
 assert.deepEqual(FILM.scenes.map(s=>[s.start,s.end]),[[0,15],[15,35],[35,75],[75,95],[95,115],[115,150]]);
 assert.deepEqual(FILM.scenes.map(s=>s.part),['BUSINESS PAIN','BUSINESS PAIN','BUSINESS PAIN','VALUE PROPOSITION','VALUE PROPOSITION','VALUE PROPOSITION']);
});
test('every title, caption and part label is English and time-addressable',()=>{
 for(const s of FILM.scenes){
  for(const value of [s.title,s.part,...s.notes])assert.match(value,/^[\x20-\x7e]+$/);
  assert.equal(shotAt(s.start).id,s.id);
  for(let t=s.start;t<s.end;t+=.37)assert.ok(s.notes.includes(noteAt(t)));
 }
 assert.equal(shotAt(150).id,'singapore');assert.equal(shotAt(-1).id,'valve');
});
test('camera references are not mislabeled as 8K RED footage or actual business events',()=>{
 assert.match(FILM.cameraReference,/visual reference only/);assert.match(FILM.cameraReference,/1920x1080/);
 assert.match(FILM.scope,/No live incidents/);assert.match(FILM.scope,/Apple\/RED affiliation/);
 assert.equal(FILM.speech,false);assert.equal(FILM.kling,false);
 assert.match(FILM.scenes[2].notes.join(' '),/conceptual imagery, not integrated live feeds/);
});
test('the renderer has real 3D cameras, reflective geometry and a full-frame encoder',()=>{
 const film=fs.readFileSync(new URL('../media/cinematic/film.mjs',import.meta.url),'utf8');
 assert.match(film,/new T\.WebGLRenderer/);assert.match(film,/new T\.PerspectiveCamera/);assert.match(film,/new Reflector/);
 assert.match(film,/new T\.MeshPhysicalMaterial/);assert.match(film,/new T\.ExtrudeGeometry/);
 assert.match(film,/Math\.PI\*clamp\(u\/35\)/);assert.match(film,/\(end-start\)\*fps/);assert.match(film,/new VideoFrame/);
 assert.ok(!film.includes('/api/'));assert.ok(!film.includes('klingai'));
});
test('narrative explicitly preserves advisory, review and delivery boundaries',()=>{
 const text=FILM.scenes.flatMap(s=>s.notes).join(' ');
 assert.match(text,/human outcome separately/);assert.match(text,/Model candidates remain advisory/);
 assert.match(text,/preview does not move a vehicle/);assert.match(text,/never at a hospital/);
});
test('camera easing stays within finite monotone interpolation bounds',()=>{
 assert.equal(ease(-1),0);assert.equal(ease(2),1);
 let last=0;for(let i=0;i<=100;i++){const v=ease(i/100);assert.ok(Number.isFinite(v)&&v>=last&&v<=1);last=v;}
});
