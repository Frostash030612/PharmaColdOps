import {STORY,sceneAt,noteAt} from './story.mjs';

export const C={bg:'#06131F',ink:'#F2F7FB',dim:'#9BB0C2',cyan:'#61D6ED',gold:'#FFD27A',red:'#FF837C',green:'#8FE3BD',line:'#244052'};
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const ease=x=>{x=clamp(x);return x*x*(3-2*x);};
const mix=(a,b,t)=>a+(b-a)*t;
const reveal=(t,a,d=.8)=>ease((t-a)/d);

export function drawFrame(ctx,time,{diagnostics=false}={}){
 const t=clamp(time,0,STORY.duration-1e-6),scene=sceneAt(t),u=t-scene.start;
 const boxes=[];let opacity=1;
 ctx.resetTransform();ctx.globalAlpha=1;ctx.clearRect(0,0,1920,1080);
 const bg=ctx.createRadialGradient(1000,480,40,1000,480,1400);bg.addColorStop(0,'#102D3E');bg.addColorStop(1,C.bg);ctx.fillStyle=bg;ctx.fillRect(0,0,1920,1080);
 ctx.strokeStyle='#FFFFFF';ctx.lineWidth=1;ctx.globalAlpha=.035;
 for(let x=-80;x<2000;x+=80){ctx.beginPath();ctx.moveTo(x+(t*3)%80,160);ctx.lineTo(x+(t*3)%80,900);ctx.stroke();}
 for(let y=170;y<940;y+=80){ctx.beginPath();ctx.moveTo(70,y);ctx.lineTo(1850,y);ctx.stroke();}
 ctx.globalAlpha=1;
 function text(value,x,y,{size=30,color=C.ink,bold=false,align='left',alpha=1}={}){
   ctx.save();ctx.globalAlpha*=alpha;ctx.fillStyle=color;ctx.font=`${bold?'700':'400'} ${size}px Arial`;ctx.textAlign=align;ctx.textBaseline='alphabetic';
   const m=ctx.measureText(value),w=m.width;
   if(diagnostics&&ctx.globalAlpha>.25){const tr=ctx.getTransform();const left=x-(align==='center'?w/2:align==='right'?w:0);boxes.push({text:value,x:tr.a*left+tr.e,y:tr.d*(y-size*.82)+tr.f,w:Math.abs(tr.a*w),h:Math.abs(tr.d*size*1.08)});}
   ctx.fillText(value,x,y);ctx.restore();
 }
 function line(points,color=C.cyan,width=3,p=1,dash=[]){
   if(points.length<2||p<=0)return;
   ctx.save();ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.lineJoin='round';ctx.setLineDash(dash);
   let lengths=[],total=0;for(let i=1;i<points.length;i++){const n=Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]);lengths.push(n);total+=n;}
   let remaining=total*clamp(p);ctx.beginPath();ctx.moveTo(...points[0]);
   for(let i=1;i<points.length&&remaining>0;i++){const k=Math.min(1,remaining/(lengths[i-1]||1));ctx.lineTo(mix(points[i-1][0],points[i][0],k),mix(points[i-1][1],points[i][1],k));remaining-=lengths[i-1];}
   ctx.stroke();ctx.restore();
 }
 function dot(x,y,r=6,color=C.cyan,glow=0){ctx.save();ctx.fillStyle=color;ctx.shadowColor=color;ctx.shadowBlur=glow;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();ctx.restore();}
 function ring(x,y,r,color=C.cyan,width=3,p=1){ctx.save();ctx.translate(x,y);ctx.rotate(-Math.PI/2);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.beginPath();ctx.arc(0,0,r,0,Math.PI*2*clamp(p));ctx.stroke();ctx.restore();}
 function rect(x,y,w,h,fill='#102B3A',stroke=null,r=16){ctx.save();ctx.beginPath();ctx.roundRect(x,y,w,h,r);if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.stroke();}ctx.restore();}
 function arrow(a,b,p=1,color=C.cyan,width=3){line([a,b],color,width,p);if(p>.96){const angle=Math.atan2(b[1]-a[1],b[0]-a[0]);line([[b[0]-15*Math.cos(angle-.45),b[1]-15*Math.sin(angle-.45)],b,[b[0]-15*Math.cos(angle+.45),b[1]-15*Math.sin(angle+.45)]],color,width);}}
 function chip(label,x,y,w=210,color=C.cyan){rect(x,y,w,49,'#102C3B',null,24);dot(x+23,y+25,4,color);text(label,x+43,y+33,{size:23,color});}
 function card(label,sub,x,y,w=340,color=C.cyan){rect(x,y,w,128,'#0D2432',C.line,15);line([[x,y+26],[x,y+98]],color,4);text(label,x+27,y+50,{size:28,bold:true,color});if(sub)text(sub,x+27,y+90,{size:22,color:C.dim});}
 function vial(x,y,s=1,temperature=5){
   ctx.save();ctx.translate(x,y);ctx.scale(s,s);
   rect(-58,-152,116,30,'#7EA7BA',null,5);rect(-45,-120,90,25,'#284959',C.cyan,4);
   ctx.beginPath();ctx.moveTo(-40,-95);ctx.quadraticCurveTo(-70,-70,-70,-44);ctx.lineTo(-70,123);ctx.quadraticCurveTo(-70,149,-44,149);ctx.lineTo(44,149);ctx.quadraticCurveTo(70,149,70,123);ctx.lineTo(70,-44);ctx.quadraticCurveTo(70,-70,40,-95);ctx.closePath();ctx.fillStyle='#153D50';ctx.fill();ctx.strokeStyle=C.cyan;ctx.lineWidth=3;ctx.stroke();
   const warm=temperature>8;ctx.fillStyle=warm?'#773D43':'#216B85';ctx.beginPath();ctx.roundRect(-60,24,120,114,15);ctx.fill();
   rect(-60,-25,120,68,'#DDECF1',null,3);line([[-15,9],[15,9]],'#143E51',6);line([[0,-6],[0,24]],'#143E51',6);
   line([[-49,-73],[-49,-43]],'#73A8BA',4);line([[-49,66],[-49,115]],'#73A8BA',3);ctx.restore();
 }
 function warehouse(x,y,{color=C.cyan,selected=false,scale=1}={}){ctx.save();ctx.translate(x,y);ctx.scale(scale,scale);ctx.fillStyle=selected?'#173C38':'#102B3B';ctx.beginPath();ctx.moveTo(-49,-12);ctx.lineTo(0,-48);ctx.lineTo(49,-12);ctx.closePath();ctx.fill();line([[-49,-12],[0,-48],[49,-12]],color,4);rect(-43,-12,86,61,selected?'#173C38':'#102B3B',color,3);rect(-12,15,24,34,C.bg,color,1);line([[-30,5],[-19,5]],color,3);line([[19,5],[30,5]],color,3);ctx.restore();}
 function hospital(x,y,{scale=1,color=C.dim}={}){ctx.save();ctx.translate(x,y);ctx.scale(scale,scale);rect(-32,-31,64,70,'#0E2A39',color,7);line([[-12,-8],[12,-8]],color,5);line([[0,-20],[0,4]],color,5);line([[-17,20],[-10,20]],color,3);line([[10,20],[17,20]],color,3);ctx.restore();}
 function truck(x,y,{scale=1,color=C.cyan,angle=0}={}){ctx.save();ctx.translate(x,y);ctx.rotate(angle);ctx.scale(scale,scale);rect(-42,-25,61,43,'#164759',color,5);rect(19,-12,29,30,'#163C4D',color,4);line([[29,-8],[39,-8],[43,1],[29,1],[29,-8]],color,2);dot(-22,22,9,C.bg);ring(-22,22,9,color,3);dot(30,22,9,C.bg);ring(30,22,9,color,3);ctx.restore();}
 function follow(points,p){let sum=0,ls=[];for(let i=1;i<points.length;i++){let d=Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]);sum+=d;ls.push(d);}let left=clamp(p)*sum;for(let i=1;i<points.length;i++){if(left<=ls[i-1]||i===points.length-1){const k=clamp(left/ls[i-1]);return{x:mix(points[i-1][0],points[i][0],k),y:mix(points[i-1][1],points[i][1],k),angle:Math.atan2(points[i][1]-points[i-1][1],points[i][0]-points[i-1][0])};}left-=ls[i-1];}}
 function packet(points,p,color=C.cyan){line(points,C.line,2);const v=follow(points,p);dot(v.x,v.y,7,color,16);}
 function withAlpha(a,fn){ctx.save();ctx.globalAlpha*=clamp(a);fn();ctx.restore();}
 function labelLines(value,x,y,{size=34,width=1580,color=C.ink,align='left',bold=false,lineHeight=46}={}){ctx.save();ctx.font=`${bold?'700':'400'} ${size}px Arial`;const words=value.split(' ');let row='',rows=[];for(const word of words){const trial=row?row+' '+word:word;if(ctx.measureText(trial).width>width&&row){rows.push(row);row=word;}else row=trial;}if(row)rows.push(row);rows.forEach((row,i)=>text(row,x,y+i*lineHeight,{size,color,align,bold}));ctx.restore();return rows.length;}

 // The persistent editorial frame is separate from the animated concept.
 text('PHARMACOLDOPS',90,65,{size:22,bold:true,color:C.cyan});
 text('BEYOND THE TEMPERATURE ALARM',1830,65,{size:19,color:C.dim,align:'right'});
 line([[90,92],[1830,92]],C.line,1);line([[90,92],[90+1740*t/90,92]],C.cyan,2);
 text(scene.tag,90,150,{size:19,color:C.gold});
 const titleEnter=reveal(u,0,.65);
 withAlpha(titleEnter,()=>text(scene.title,90,228+18*(1-titleEnter),{size:scene.id==='close'?72:58,bold:true}));
 opacity=Math.min(reveal(u,.1,.5),1-reveal(u,scene.end-scene.start-.35,.35));
 ctx.save();ctx.globalAlpha=opacity;

 if(scene.id==='alarm'){
   const heat=reveal(u,1.1,1.9),temp=mix(5,20,heat),pulse=.5+.5*Math.sin(t*4);
   for(let i=0;i<3;i++)withAlpha(.18*(1-(u*.3+i*.3)%1),()=>ring(960,555,160+((u*.3+i*.3)%1)*130,heat>.4?C.red:C.cyan,2));
   vial(960,560,1.12,temp);chip(`${temp.toFixed(0)} C`,1110,443,142,heat>.4?C.red:C.cyan);
   withAlpha(reveal(u,2.4,.5),()=>{
     for(const [label,x,y]of[['Quality?',460,470],['Supply?',1410,470],['Evidence?',960,800]]){const dest=[x,y-30];arrow([960+(x-960)*.17,555+(y-555)*.17],dest,reveal(u,2.6,.8),C.gold,2);rect(x-114,y-55,228,76,'#0C2432',C.line);text(label,x,y-6,{align:'center',size:32,bold:true});}
   });
   text('TEMPERATURE EXCURSION',960,350,{align:'center',size:22,color:heat>.4?C.red:C.dim});
 }else if(scene.id==='exposure'){
   const x0=245,y0=792,w=1380,h=405;const px=n=>x0+w*n/120,py=n=>y0-h*n/24;
   const bandTop=py(8),bandBottom=py(2);rect(x0,bandTop,w,bandBottom-bandTop,'#123B4B',null,0);
   for(const value of [0,8,16,24]){line([[x0,py(value)],[x0+w,py(value)]],C.line,1);text(String(value),x0-25,py(value)+9,{align:'right',size:23,color:C.dim});}
   arrow([x0,y0],[x0+w+20,y0],reveal(u,.1,.8),C.dim,2);arrow([x0,y0],[x0,py(24)-25],reveal(u,.1,.8),C.dim,2);
   for(const value of [0,30,60,90,120]){text(String(value),px(value),y0+38,{align:'center',size:23,color:C.dim});}
   text('TIME (MINUTES)',x0+w/2,y0+79,{align:'center',size:23,color:C.dim});text('TEMPERATURE (C)',x0,326,{size:23,color:C.dim});
   text('2-8 C prototype band',x0+w-20,py(8)+37,{align:'right',size:23,color:C.cyan});
   withAlpha(.28*reveal(u,3,1),()=>rect(px(15),py(20),px(105)-px(15),y0-py(20),C.red,null,0));
   const points=[[px(0),py(5)],[px(15),py(5)],[px(15),py(20)],[px(105),py(20)],[px(105),py(5)],[px(120),py(5)]];
   const p=reveal(u,.8,4.7);line(points,C.cyan,5,p);const marker=follow(points,p);dot(marker.x,marker.y,8,C.cyan,18);
   withAlpha(reveal(u,4.4,1),()=>{chip('HOT WINDOW',605,296,228,C.red);text(`${Math.round(90*reveal(u,4.4,1.1))} min`,860,331,{size:39,bold:true,color:C.red});chip('WINDOW MKT  20.0 C',1170,296,358,C.gold);});
   withAlpha(reveal(u,6.5,.6),()=>{line([[px(15),py(20)-38],[px(105),py(20)-38]],C.gold,3);dot(px(15),py(20)-38,4,C.gold);dot(px(105),py(20)-38,4,C.gold);});
 }else if(scene.id==='rules'){
   const path=[[470,512],[700,512]];
   withAlpha(reveal(u,.5),()=>{vial(320,545,.64,20);text('SIMULATED INPUT',320,355,{align:'center',size:23,color:C.dim});text('20 C / 90 min',320,727,{align:'center',size:30,bold:true});});
   withAlpha(reveal(u,1),()=>{rect(710,404,340,218,'#102A38',C.cyan,24);text('RULE 3',880,455,{align:'center',size:24,color:C.cyan});text('90 min',880,515,{align:'center',size:48,bold:true});text('>= 2 x 30 min',880,565,{align:'center',size:30,color:C.gold});text('30 min = demo assumption',880,668,{align:'center',size:22,color:C.dim});});
   arrow([470,512],[710,512],reveal(u,1,1),C.cyan,3);arrow([1050,512],[1270,512],reveal(u,2.5,1),C.red,3);
   withAlpha(reveal(u,3,.7),()=>{rect(1270,424,380,175,'#38282D',C.red,22);text('SCRAP',1460,500,{align:'center',size:58,bold:true,color:C.red});text('Prototype recommendation',1460,553,{align:'center',size:23,color:C.dim});});
   withAlpha(reveal(u,5,.8),()=>{line([[880,710],[880,773],[1270,773]],C.line,2,1,[7,7]);chip('ADVISORY MODEL',505,747,310,C.gold);text('No medicine-disposition authority',1300,787,{size:25,color:C.gold});ring(1250,773,15,C.gold,2);line([[1240,783],[1260,763]],C.gold,2);});
   withAlpha(reveal(u,1,1),()=>{const p=follow(path,(u*.19)%1);dot(p.x,p.y,5,C.cyan,10);});
 }else if(scene.id==='review'){
   const unlocked=u>=5.2;
   card('ORIGINAL SNAPSHOT','Immutable prototype advice',175,410,420,C.cyan);text('SCRAP',210,604,{size:42,bold:true,color:C.red});
   const gateX=952,gateY=482;ring(gateX,gateY,83,unlocked?C.green:C.gold,4,reveal(u,.8,.8));
   // A deliberately abstract person marker, not an identity or signature.
   dot(gateX,gateY-22,15,unlocked?C.green:C.gold);ctx.save();ctx.strokeStyle=unlocked?C.green:C.gold;ctx.lineWidth=5;ctx.beginPath();ctx.arc(gateX,gateY+25,30,Math.PI,0);ctx.stroke();ctx.restore();
   text(unlocked?'REVIEW LOGGED':'PENDING REVIEW',gateX,625,{align:'center',size:27,bold:true,color:unlocked?C.green:C.gold});
   arrow([605,477],[855,477],reveal(u,1,1),C.gold,3);arrow([1046,477],[1290,477],unlocked?reveal(u,5.2,.7):1,unlocked?C.green:C.line,3);
   if(!unlocked){line([[1172,435],[1172,521]],C.gold,6);ring(1172,422,11,C.gold,3);}
   card('EFFECTIVE OUTCOME',unlocked?'Illustration - reviewed scrap':'Execution is blocked',1290,410,440,unlocked?C.green:C.gold);
   withAlpha(reveal(u,5.2,.7),()=>text('SCRAP',1325,604,{size:42,bold:true,color:C.red}));
   line([[390,720],[1510,720]],C.line,2);text('Original advice is preserved',390,770,{align:'center',size:24,color:C.dim});text('The review is a separate record',1400,770,{align:'center',size:24,color:C.dim});
   truck(mix(990,1420,reveal(u,6.3,2)),699,{scale:.63,color:unlocked?C.green:C.gold});
 }else if(scene.id==='routes'){
   const nodes={w:[265,705],a:[520,395],b:[900,348],c:[1248,570],n:[930,750],p:[1260,760]};
   const old=[nodes.w,nodes.a,nodes.b,nodes.c,nodes.p];
   const replacement=[nodes.w,[540,705],nodes.n,[1120,750],nodes.p];
   line(old,C.line,3,1,[9,10]);line([nodes.w,nodes.a],C.dim,4);
   for(const [key,point]of Object.entries(nodes)){
     if(['w','p'].includes(key))warehouse(...point,{scale:.72,color:key==='p'?C.green:C.cyan,selected:key==='p'});else hospital(...point,{scale:.68,color:key==='n'?C.gold:key==='a'?C.dim:C.cyan});
   }
   text('PICKUP WAREHOUSE',265,788,{align:'center',size:20,color:C.cyan});text('COMPLETED',520,465,{align:'center',size:20,color:C.dim});
   text('EXISTING STOPS',900,285,{align:'center',size:22,color:C.dim});text('REPLACEMENT',930,829,{align:'center',size:21,color:C.gold});text('ALLOWED TERMINAL',1270,829,{align:'center',size:20,color:C.green});
   const adopted=u>=5.4,done=u>=10.6;line(replacement,adopted?C.green:C.gold,4,reveal(u,.8,2.5),adopted?[]:[9,9]);
   if(u>5.4){const v=follow(replacement,reveal(u,5.4,5.2));truck(v.x,v.y,{scale:.62,color:C.green,angle:v.angle});}
   const labels=['Delivery windows','Temperature zone','Available fleet','Completed work','Allowed terminal'];
   labels.forEach((label,i)=>withAlpha(reveal(u,.5+i*.45,.5),()=>{dot(1500,362+i*69,5,C.cyan);text(label,1522,370+i*69,{size:25,color:C.dim});}));
   chip(done?'DELIVERED':adopted?'ADOPTED':'PREVIEW',1465,753,300,done?C.green:adopted?C.cyan:C.gold);
   text('Illustrated execution state',1615,837,{align:'center',size:20,color:C.dim});
   withAlpha(reveal(u,10.6,.5),()=>{ring(...nodes.n,52,C.green,3);dot(...nodes.n,8,C.green,15);});
 }else if(scene.id==='parking'){
   const names=['Westgate','Pioneer','Northpoint','Hougang','Bugis'];
   for(let i=0;i<14;i++){const x=210+i*114,y=374+Math.sin(i*.49)*35;withAlpha(reveal(u,.05*i,.5),()=>{hospital(x,y,{scale:.48,color:C.dim});});}
   text('14 receiving hospitals',960,481,{align:'center',size:27,color:C.dim});
   names.forEach((name,i)=>{const x=310+i*325,selected=[2,3].includes(i);withAlpha(reveal(u,.7+i*.17,.6),()=>{
     warehouse(x,670,{selected,color:selected?C.green:C.dim,scale:.9});text(name,x,775,{align:'center',size:26,color:selected?C.green:C.dim});
     if(selected){ring(x+67,620,15,C.green,2);line([[x+58,620],[x+65,627],[x+78,611]],C.green,3);}
   });});
   const p=reveal(u,3,2.2),start=[1236,410],end=[1285,670];line([start,[1435,530],end],C.green,3,p);const v=follow([start,[1435,530],end],p);truck(v.x,v.y-20,{scale:.58,color:C.green});
   withAlpha(reveal(u,2.6,.6),()=>chip('SELECTED SUBSET',796,826,330,C.green));
 }else if(scene.id==='evidence'){
   const sources=[['CASE',245],['REVIEW',490],['DELIVERY',735]];
   sources.forEach(([label,x],i)=>withAlpha(reveal(u,i*.45,.5),()=>{rect(x-93,316,186,65,'#10313B',C.line,12);text(label,x,358,{align:'center',size:25,bold:true,color:C.cyan});arrow([x,389],[490,455],1,C.line,2);}));
   rect(280,455,420,110,'#12352F',C.green,17);text('Authoritative case store',490,503,{align:'center',size:29,bold:true,color:C.green});text('Original + review + delivery',490,543,{align:'center',size:22,color:C.dim});
   const gnodes=[[855,681,'Event'],[1100,632,'Rule'],[1100,781,'Reference']];
   withAlpha(reveal(u,2.1,.7),()=>{line([[855,681],[1100,632],[1100,781]],C.cyan,2);gnodes.forEach(([x,y,label])=>{dot(x,y,38,'#0B2432');ring(x,y,38,C.cyan,2);dot(x,y,6,C.cyan);text(label,label==='Rule'?x+73:x,label==='Rule'?y+8:y+68,{align:label==='Rule'?'left':'center',size:23,color:C.dim});});text('Derived evidence graph',1000,892,{align:'center',size:25,color:C.cyan});});
   withAlpha(reveal(u,2.4,.7),()=>{line([[700,515],[855,515],[855,638]],C.line,2,1,[6,7]);text('replayable mirror',848,474,{align:'center',size:21,color:C.dim});});
   withAlpha(reveal(u,4.4,.7),()=>{
     arrow([710,510],[1430,510],reveal(u,4.4,.8),C.green,2);arrow([1140,681],[1430,570],reveal(u,4.8,.8),C.cyan,2);
     rect(1430,410,295,260,'#0D2938',C.cyan,19);line([[1645,410],[1645,470],[1725,470]],C.cyan,2);text('CASE AUDIT',1577,531,{align:'center',size:29,bold:true});text('HTML + JSON',1577,589,{align:'center',size:24,color:C.cyan});
   });
   withAlpha(reveal(u,5.5,.6),()=>text('Graph questions explain original evidence; review history stays separate.',960,285,{align:'center',size:23,color:C.gold}));
 }else if(scene.id==='benchmark'){
   const b=STORY.routeBenchmark,reduction=(1-b.optimizedKm/b.greedyKm)*100;
   const p=reveal(u,.7,2.5),base=793,scale=2.22;
   for(const [label,km,x,color]of[['Greedy',b.greedyKm,565,C.dim],['OR-Tools GLS',b.optimizedKm,1125,C.cyan]]){
     const h=km*scale*p;rect(x-125,base-h,250,h,color,null,5);text(`${(km*p).toFixed(2)} km`,x,base-h-30,{align:'center',size:42,bold:true,color});text(label,x,base+52,{align:'center',size:30});text('3 vehicles',x,base+93,{align:'center',size:22,color:C.dim});
   }
   line([[290,base],[1370,base]],C.line,2);text('TOTAL DISTANCE',290,336,{size:22,color:C.dim});
   withAlpha(reveal(u,3.3,.6),()=>{text(`-${reduction.toFixed(2)}%`,1590,480,{align:'center',size:65,bold:true,color:C.green});text('same-fleet distance',1590,531,{align:'center',size:24,color:C.dim});});
   withAlpha(reveal(u,5.6,.6),()=>{rect(1415,620,350,140,'#302C2E',null,14);text('Not operating savings',1590,678,{align:'center',size:26,bold:true,color:C.gold});text('One frozen static instance',1590,720,{align:'center',size:22,color:C.dim});});
 }else if(scene.id==='close'){
   const p=reveal(u,.4,1.2);const center=[960,565],r=195,labels=['OBSERVE','REVIEW','DELIVER','EXPLAIN'];
   const points=labels.map((label,i)=>{const a=-Math.PI/2+i*Math.PI/2;return[center[0]+r*Math.cos(a),center[1]+r*Math.sin(a)];});
   points.forEach((point,i)=>{const next=points[(i+1)%4];line([point,next],C.line,2,p);const k=(u*.15+i*.25)%1;packet([point,next],k,C.cyan);dot(...point,8,i===1?C.gold:C.cyan,14);const tx=point[0]+(i===1?120:i===3?-120:0),ty=point[1]+(i===0?-42:i===2?54:7);text(labels[i],tx,ty,{align:'center',size:24,bold:true,color:i===1?C.gold:C.cyan});});
   vial(...center,.58,5);
   withAlpha(reveal(u,2.2,.7),()=>{text('An inspectable handover.',960,861,{align:'center',size:33,bold:true});});
 }
 ctx.restore();

 // Explanatory notes, not a transcript of a human or AI speaker.
 line([[90,923],[1830,923]],C.line,1);
 const note=noteAt(t);labelLines(note,960,972,{size:31,width:1650,align:'center',lineHeight:40});
 text(scene.scope,960,1050,{align:'center',size:17,color:C.dim});
 return{scene:scene.id,time:t,note,textBounds:boxes};
}
