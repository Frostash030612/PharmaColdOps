/* Deterministic Canvas animation -> native PNG/raw RGBA -> H.264.
   No video generation service, model, browser-state injection or app writes. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {STORY,sceneAt} from '../media/explainer/story.mjs';
import {drawFrame} from '../media/explainer/scene.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const args={};
for(let i=2;i<process.argv.length;i++){
 if(process.argv[i]==='--help'){console.log('Required: --runtime-modules PATH --output NEW_DIRECTORY. Optional: --ffmpeg PATH --fps 60 --preview-only --font PATH --bold-font PATH. Outputs stay under data/processed.');process.exit(0);}
 const key=process.argv[i].slice(2);if(key==='preview-only')args[key]=true;else{if(!process.argv[i].startsWith('--')||!process.argv[i+1])throw Error('invalid arguments');args[key]=process.argv[++i];}
}
for(const key of ['runtime-modules','output'])if(!args[key])throw Error('missing --'+key);
const output=path.resolve(args.output);
if(!output.startsWith(path.join(root,'data/processed')+path.sep))throw Error('new output must be under data/processed');
try{await fs.access(output);throw Error('fresh output required');}catch(e){if(e.code!=='ENOENT')throw e;}
const fps=Number(args.fps||60);if(![30,60].includes(fps))throw Error('use 30 or 60 fps');
if(!args['preview-only']&&!args.ffmpeg)throw Error('ffmpeg path required');
const require=createRequire(path.join(path.resolve(args['runtime-modules']),'resolve.cjs'));
const {createCanvas,GlobalFonts}=require('@napi-rs/canvas');
for(const font of [args.font||'/System/Library/Fonts/Supplemental/Arial.ttf',args['bold-font']||'/System/Library/Fonts/Supplemental/Arial Bold.ttf']){
 if(!GlobalFonts.registerFromPath(font,'Arial'))throw Error('font registration failed');
}
await fs.mkdir(output,{recursive:true});await fs.mkdir(path.join(output,'frames'));
const canvas=createCanvas(STORY.width,STORY.height),ctx=canvas.getContext('2d');
const report={schema:'pharmacoldops-code-explainer-v1',status:'rendering',width:STORY.width,height:STORY.height,fps,durationSeconds:STORY.duration,
 language:'en',method:'deterministic code-drawn Canvas; no Kling or video generation model',spokenNarration:false,
 sourceApplicationCommit:STORY.sourceApplicationCommit,workflowIsIllustrative:true,submissionReady:false,frames:[],findings:[]};
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
for(const file of ['media/explainer/story.mjs','media/explainer/scene.mjs'])report[file+'Sha256']=hash(await fs.readFile(path.join(root,file)));
const times=STORY.scenes.flatMap(s=>[s.start+.8,s.start+Math.min(3,(s.end-s.start)/2),s.end-.8]);
try{
 for(let i=0;i<times.length;i++){
   const time=times[i],frame=drawFrame(ctx,time,{diagnostics:true});
   const bad=frame.textBounds.filter(b=>b.x<55||b.y<15||b.x+b.w>1865||b.y+b.h>1078);
   if(bad.length)report.findings.push({time,scene:frame.scene,kind:'text_outside_safe_frame',items:bad});
   const name=`frame-${String(i+1).padStart(2,'0')}.png`;
   await fs.writeFile(path.join(output,'frames',name),canvas.toBuffer('image/png'));
   report.frames.push({time,scene:frame.scene,file:'frames/'+name});
 }
 if(report.findings.length)throw Error('preview geometry findings; inspect report');
 drawFrame(ctx,3);await fs.writeFile(path.join(output,'poster.png'),canvas.toBuffer('image/png'));
 if(!args['preview-only']){
   const dest=path.join(output,'PharmaColdOps-Beyond-the-Temperature-Alarm-silent.mp4');
   const command=['-nostdin','-hide_banner','-loglevel','warning','-n','-f','rawvideo','-pix_fmt','rgba','-s',`${STORY.width}x${STORY.height}`,'-r',String(fps),'-i','pipe:0',
     '-an','-c:v','libx264','-preset','veryfast','-crf','20','-threads','6','-pix_fmt','yuv420p','-movflags','+faststart',dest];
   const encoder=spawn(path.resolve(args.ffmpeg),command,{stdio:['pipe','ignore','pipe']});
   const done=new Promise((resolve,reject)=>{encoder.on('error',reject);encoder.on('close',code=>code===0?resolve():reject(Error('ffmpeg exit '+code)));});
   // Keep rejection observed while producing frames; preserve diagnostics on failure.
   done.catch(()=>{});let encoderError='';encoder.stderr.on('data',chunk=>{encoderError+=chunk;});
   encoder.stdin.on('error',()=>{});
   for(let i=0;i<STORY.duration*fps;i++){
     drawFrame(ctx,i/fps);
     const pixels=ctx.getImageData(0,0,STORY.width,STORY.height).data;
     const buffer=Buffer.from(pixels.buffer,pixels.byteOffset,pixels.byteLength);
     if(!encoder.stdin.write(buffer))await once(encoder.stdin,'drain');
     if(i%(fps*5)===0)console.log(JSON.stringify({time:i/fps,scene:sceneAt(i/fps).id,frame:i,total:STORY.duration*fps}));
   }
   encoder.stdin.end();await done;
   await fs.writeFile(path.join(output,'encode.log'),encoderError);
   report.video=path.basename(dest);report.videoSha256=hash(await fs.readFile(dest));report.frameCount=STORY.duration*fps;
 }
 let cue=1,srt='';const stamp=x=>{const ms=Math.round(x*1000);return `00:${String(Math.floor(ms/60000)).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`;};
 for(const s of STORY.scenes)for(let i=0;i<s.notes.length;i++){const a=s.start+i*(s.end-s.start)/s.notes.length,b=s.start+(i+1)*(s.end-s.start)/s.notes.length;srt+=`${cue++}\n${stamp(a)} --> ${stamp(b-.04)}\n${s.notes[i]}\n\n`;}
 await fs.writeFile(path.join(output,'English-On-Screen-Notes.srt'),srt);
 report.status=args['preview-only']?'preview_ready':'video_encoded';
}catch(error){report.status='failed';report.error=String(error);throw error;}
finally{await fs.writeFile(path.join(output,'render-report.json'),JSON.stringify(report,null,2));}
console.log(JSON.stringify({status:report.status,output,geometryFindings:report.findings.length,frameCount:report.frameCount}));
