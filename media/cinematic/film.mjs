import * as T from 'three';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {ShaderPass} from 'three/addons/postprocessing/ShaderPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
import {Reflector} from 'three/addons/objects/Reflector.js';
import {Muxer,ArrayBufferTarget} from './vendor/mp4-muxer.mjs';
import {FILM,clamp,ease,mix,shotAt,noteAt} from './story.mjs';
import {GEO} from './geography.mjs';

const W=FILM.width,H=FILM.height,out=document.getElementById('film'),ink=out.getContext('2d'),status=document.getElementById('status');
const renderer=new T.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true,powerPreference:'high-performance'});
renderer.setSize(W,H);renderer.setPixelRatio(1);renderer.setClearColor(0x020406);renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=.8;renderer.outputColorSpace=T.SRGBColorSpace;
const pmrem=new T.PMREMGenerator(renderer),room=new RoomEnvironment();const env=pmrem.fromScene(room,.04).texture;room.dispose();pmrem.dispose();
const camera=new T.PerspectiveCamera(43,W/H,.005,1500);const scene=new T.Scene();scene.environment=env;scene.environmentIntensity=.45;scene.background=new T.Color(0x020406);scene.fog=new T.FogExp2(0x061019,.014);
scene.add(new T.HemisphereLight(0x86b9d0,0x020306,.3));
const key=new T.DirectionalLight(0xe8f7ff,1.3);key.position.set(5,9,4);scene.add(key);
const rim=new T.PointLight(0x48dfff,40,35,2);rim.position.set(-4,4,-3);scene.add(rim);
const warning=new T.PointLight(0xff2244,0,20,2);warning.position.set(.1,1.5,.3);scene.add(warning);
const composer=new EffectComposer(renderer);composer.addPass(new RenderPass(scene,camera));
const bloom=new UnrealBloomPass(new T.Vector2(W,H),.24,.35,1.25);composer.addPass(bloom);
const blur=new ShaderPass({uniforms:{tDiffuse:{value:null},amount:{value:0},radial:{value:1}},
 vertexShader:'varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
 fragmentShader:'uniform sampler2D tDiffuse;uniform float amount;uniform float radial;varying vec2 vUv;void main(){vec2 d=mix(vec2(.7,.22),vUv-.5,radial)*amount;vec4 c=vec4(0.);for(int i=0;i<7;i++){float f=(float(i)-3.)/3.;c+=texture2D(tDiffuse,vUv+d*f)/7.;}gl_FragColor=c;}' });composer.addPass(blur);composer.addPass(new OutputPass());

const V=(x=0,y=0,z=0)=>new T.Vector3(x,y,z);const root=new T.Group();scene.add(root);
const metal=new T.MeshPhysicalMaterial({color:0x9aadb5,metalness:1,roughness:.22,clearcoat:.5,clearcoatRoughness:.12,envMapIntensity:.9});
const dark=new T.MeshPhysicalMaterial({color:0x111c23,metalness:.95,roughness:.26,clearcoat:.25,envMapIntensity:.65});
const black=new T.MeshStandardMaterial({color:0x03080c,metalness:.82,roughness:.3});
const cyan=new T.MeshStandardMaterial({color:0x63eaff,emissive:0x27caff,emissiveIntensity:1.5,metalness:.25,roughness:.25});
const red=new T.MeshStandardMaterial({color:0xff2853,emissive:0xff1236,emissiveIntensity:1.7});
const white=new T.MeshStandardMaterial({color:0xe9f8ff,emissive:0xa2e5ff,emissiveIntensity:1.3});
const meshes=[];
function mesh(geometry,material,parent=root,pos=[0,0,0]){const o=new T.Mesh(geometry,material);o.position.set(...pos);parent.add(o);meshes.push(o);return o;}
function box(w,h,d,mat,parent=root,pos=[0,0,0],radius=.04){return mesh(new RoundedBoxGeometry(w,h,d,2,Math.min(radius,w/5,h/5,d/5)),mat,parent,pos);}
function cylinder(a,b,h,mat,parent,pos){return mesh(new T.CylinderGeometry(a,b,h,48),mat,parent,pos);}
function torus(r,tube,mat,parent,pos=[0,0,0]){return mesh(new T.TorusGeometry(r,tube,12,72),mat,parent,pos);}
function line(points,color=0x58dfff,parent=root,opacity=1){const g=new T.BufferGeometry().setFromPoints(points);const m=new T.LineBasicMaterial({color,transparent:opacity<1,opacity});const o=new T.Line(g,m);parent.add(o);return o;}
function tube(points,radius,mat,parent=root){const curve=new T.CatmullRomCurve3(points);const o=mesh(new T.TubeGeometry(curve,Math.max(12,points.length*4),radius,6,false),mat,parent);return{mesh:o,curve};}
function studioFloor(parent,size=80,y=-.03){const o=mesh(new T.PlaneGeometry(size,size),new T.MeshPhysicalMaterial({color:0x02070b,metalness:.7,roughness:.3,clearcoat:.15,envMapIntensity:.12}),parent,[0,y,0]);o.rotation.x=-Math.PI/2;return o;}
function beam(parent,x,y,z,color=0x69daff,height=5,radius=1){const mat=new T.ShaderMaterial({transparent:true,depthWrite:false,side:T.DoubleSide,blending:T.AdditiveBlending,
 uniforms:{color:{value:new T.Color(color)}},vertexShader:'varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
 fragmentShader:'uniform vec3 color;varying vec2 vUv;void main(){float a=pow(1.-vUv.y,2.)*.035;gl_FragColor=vec4(color,a);}'});
 return mesh(new T.ConeGeometry(radius,height,28,1,true),mat,parent,[x,y-height/2,z]);}
function labelSprite(text,color='#bbecff'){const c=document.createElement('canvas');c.width=512;c.height=80;const q=c.getContext('2d');q.font='26px Arial';q.textAlign='center';q.fillStyle=color;q.fillText(text,256,47);const tex=new T.CanvasTexture(c);tex.colorSpace=T.SRGBColorSpace;const sp=new T.Sprite(new T.SpriteMaterial({map:tex,transparent:true,depthWrite:false}));sp.scale.set(2.8,.44,1);return sp;}
function seeded(n){const x=Math.sin(n*127.1+41.7)*43758.5453123;return x-Math.floor(x);}
const worlds=Array.from({length:6},()=>{const g=new T.Group();root.add(g);return g;});

// 0 - a physically modelled valve, then its surrounding abstract warehouse.
const warehouse=worlds[0];studioFloor(warehouse,50);
for(let z=-9;z<=9;z+=3)for(const x of [-3.2,3.2]){
 box(1.15,3.7,.95,dark,warehouse,[x,1.85,z]);
 for(let y=.4;y<3.6;y+=.65){box(1.08,.035,.98,metal,warehouse,[x,y,z]);box(.025,.12,.45,cyan,warehouse,[x-Math.sign(x)*.59,y+.15,z]);}
}
for(const x of [-5,-1.5,1.5,5]){line([V(x,.01,-14),V(x,.01,14)],0x244958,warehouse);beam(warehouse,x,5,-1,0x70ceff,5,1.6);}
const valve=new T.Group();valve.position.y=1.25;warehouse.add(valve);
const barrel=cylinder(.075,.075,.46,metal,valve,[0,0,0]);barrel.rotation.z=Math.PI/2;
for(const x of [-.20,-.145,.145,.2]){const ring=torus(.083,.011,metal,valve,[x,0,0]);ring.rotation.y=Math.PI/2;}
cylinder(.1,.1,.115,metal,valve,[0,.012,0]);cylinder(.026,.026,.16,metal,valve,[0,.13,0]);
const wheel=torus(.102,.012,metal,valve,[0,.228,0]);wheel.rotation.x=Math.PI/2;
for(let i=0;i<6;i++){const a=i*Math.PI/3;tube([V(0,.228,0),V(Math.cos(a)*.1,.228,Math.sin(a)*.1)],.0045,metal,valve);}
box(.12,.08,.07,dark,valve,[.25,.015,0]);box(.016,.022,.075,cyan,valve,[.305,.025,0],.002);
const pipeLeft=cylinder(.035,.035,1.6,metal,warehouse,[-.9,1.25,0]);pipeLeft.rotation.z=Math.PI/2;
const pipeRight=cylinder(.035,.035,1.6,metal,warehouse,[1.1,1.25,0]);pipeRight.rotation.z=Math.PI/2;
const laser=box(1.1,.003,.006,red,valve,[0,.01,.09],.001);
const laserGlow=mesh(new T.PlaneGeometry(1.3,.13),new T.MeshBasicMaterial({color:0xff1d4f,transparent:true,opacity:.06,blending:T.AdditiveBlending,depthWrite:false}),valve,[0,.01,.105]);

// 1 - abstract server/data infrastructure. No recorded real outage is implied.
const data=worlds[1];studioFloor(data,100);
const leds=[];
for(let i=0;i<18;i++)for(const side of [-1,1]){
 const rack=new T.Group();rack.position.set(side*1.8,0,6-i*2);data.add(rack);box(.8,3.4,1.25,dark,rack,[0,1.7,0]);
 for(let j=0;j<7;j++){box(.75,.025,1.3,metal,rack,[0,.35+j*.42,0]);const led=box(.016,.09,.65,j%3?cyan:red,rack,[-side*.412,.45+j*.42,0],.003);leds.push(led);}
}
for(let z=-34;z<12;z+=1.5)line([V(-5,.03,z),V(5,.03,z)],0x173b4a,data,.6);
const dataCurves=[];
for(let i=0;i<20;i++){
 const points=Array.from({length:22},(_,j)=>V(-4+i*.42,1.0+Math.sin(j*.4+i)*.5,10-j*2));
 const obj=line(points,i%4?0x3bc2e0:0xff3d63,data,.35);dataCurves.push(obj);
}
const sparkCount=220,sparkPositions=new Float32Array(sparkCount*6),sparkGeo=new T.BufferGeometry();sparkGeo.setAttribute('position',new T.BufferAttribute(sparkPositions,3));
const sparks=new T.LineSegments(sparkGeo,new T.LineBasicMaterial({color:0xffc19b,transparent:true,opacity:.8,blending:T.AdditiveBlending}));sparks.frustumCulled=false;data.add(sparks);

// 2 - a wet, explicitly fictional digital city with a real moving 3D vehicle.
const city=worlds[2];studioFloor(city,170);
const wetFloor=new Reflector(new T.PlaneGeometry(170,170),{clipBias:.003,textureWidth:960,textureHeight:540,color:0x15232b,multisample:0});
wetFloor.rotation.x=-Math.PI/2;wetFloor.position.y=-.021;city.add(wetFloor);
const cityGeometry=new T.BoxGeometry(1,1,1),cityMaterial=new T.MeshPhysicalMaterial({color:0x14202a,metalness:.85,roughness:.21,clearcoat:1});
const buildings=new T.InstancedMesh(cityGeometry,cityMaterial,260),transform=new T.Object3D();
for(let i=0;i<260;i++){
 const x=(i%20-9.5)*8,z=(Math.floor(i/20)-6)*8+4;const h=2.5+seeded(i+1)*14;
 transform.position.set(x,h/2,z);transform.scale.set(2.5+seeded(i+41)*2.7,h,3+seeded(i+61)*2);transform.rotation.y=(i%3)*.03;transform.updateMatrix();buildings.setMatrixAt(i,transform.matrix);
}city.add(buildings);
for(let i=-5;i<=5;i++){line([V(i*16,.022,-85),V(i*16,.022,85)],0x244653,city);line([V(-85,.022,i*16),V(85,.022,i*16)],0x244653,city);}
const van=new T.Group();city.add(van);box(1.6,1.45,3.0,dark,van,[0,1.15,-.3],.18);box(1.58,1.1,1.2,dark,van,[0,.97,1.65],.18);
box(1.3,.58,.035,new T.MeshPhysicalMaterial({color:0x061b26,metalness:.6,roughness:.03,clearcoat:1}),van,[0,1.25,2.27],.08);
box(1.4,.025,.025,cyan,van,[0,1.89,-.2],.006);
for(const x of [-.806,.806])box(.018,.025,2.35,cyan,van,[x,1.75,-.3],.004);
const vanFill=new T.PointLight(0x9cd8ee,5,10,2);vanFill.position.set(.3,3,-2);van.add(vanFill);
const wheels=[];
for(const x of [-.87,.87])for(const z of [-1.25,1.55]){const tire=cylinder(.36,.36,.23,black,van,[x,.38,z]);tire.rotation.z=Math.PI/2;const rimWheel=cylinder(.23,.23,.245,metal,van,[x,.38,z]);rimWheel.rotation.z=Math.PI/2;wheels.push(tire,rimWheel);}
for(const x of [-.58,.58]){box(.28,.13,.05,white,van,[x,.85,2.29],.02);const head=new T.SpotLight(0xbdeaff,2.5,20,.4,.8,1);head.position.set(x,.8,2.3);head.target.position.set(x,.03,14);van.add(head,head.target);}
const drive=new T.CatmullRomCurve3([V(-32,0,-32),V(0,0,-32),V(0,0,0),V(32,0,0),V(32,0,32),V(-32,0,32),V(-32,0,-32)],true,'catmullrom',.12);
const rainCount=3000,rainArray=new Float32Array(rainCount*6),rainGeometry=new T.BufferGeometry();rainGeometry.setAttribute('position',new T.BufferAttribute(rainArray,3));
const rain=new T.LineSegments(rainGeometry,new T.LineBasicMaterial({color:0x7da9bb,transparent:true,opacity:.32,blending:T.AdditiveBlending}));rain.frustumCulled=false;city.add(rain);

// 3 - a bespoke product core; not an Apple product or branded reference asset.
const coreWorld=worlds[3],core=new T.Group();coreWorld.add(core);
const coreBody=box(1.65,1.65,1.65,metal,core,[0,0,0],.18);coreBody.rotation.set(.38,.65,.12);
const inner=mesh(new T.IcosahedronGeometry(.85,2),dark,core);
const coreRings=[];for(let i=0;i<3;i++){const o=torus(1.5+i*.15,.026,cyan,core);o.rotation.set(i*Math.PI/3,i*.62,0);coreRings.push(o);}
for(let i=0;i<12;i++){const a=i*Math.PI/6;const bar=box(.035,.85,.035,cyan,core,[Math.cos(a)*1.14,0,Math.sin(a)*1.14],.006);bar.rotation.z=(i%2)*.08;}
// Product core remains suspended against pure black, with no bright floor.

// 4 - algorithm/evidence handover, represented as a luminous spatial network.
const algorithm=worlds[4];const networkPoints=[V(-5,1,0),V(-3,1.7,-1),V(-1,1.1,.3),V(1,1.8,-.7),V(3,1.0,.2),V(5,.1,-1),V(2,-1.6,.4),V(-1,-1.5,-1.7),V(-4,-1.2,-.6)];
const networkNodes=[],networkEdges=[],pulses=[];
const words=['Observe','Analyse','Explain','Review','Replan','Deliver','Audit'];
networkPoints.forEach((p,i)=>{const n=mesh(new T.SphereGeometry(i<7?.2:.12,32,20),i===3?white:metal,algorithm,p.toArray());networkNodes.push(n);const ring=torus(i<7?.32:.2,.009,cyan,algorithm,p.toArray());ring.rotation.x=.5;if(i<7){const label=labelSprite(words[i]);label.position.copy(p).add(V(0,-.6,0));algorithm.add(label);}});
for(let i=0;i<networkPoints.length;i++)for(let j=i+1;j<networkPoints.length;j++)if(j-i===1||(j-i===3&&i%2===0)){
 const mid=networkPoints[i].clone().lerp(networkPoints[j],.5).add(V(0,.25,-.3));const edge=tube([networkPoints[i],mid,networkPoints[j]],.012,cyan,algorithm);networkEdges.push(edge);
 const pulse=mesh(new T.SphereGeometry(.055,16,10),white,algorithm);pulses.push({mesh:pulse,curve:edge.curve,index:pulses.length});
}

// 5 - project coordinates and cached roads, with explicitly stylised buildings.
const singapore=worlds[5],mapRoot=new T.Group();singapore.add(mapRoot);
const mapPoint=([lon,lat],y=.12)=>V((lon-103.82)*500,y,-(lat-1.35)*500);
const landPolygons=GEO.land.type==='MultiPolygon'?GEO.land.coordinates:GEO.land.coordinates.map(r=>[r]);
const landRings=landPolygons.map(p=>p[0]);
for(const polygon of landPolygons){
 const outer=polygon[0].map(p=>mapPoint(p)),shape=new T.Shape();
 outer.forEach((p,i)=>i?shape.lineTo(p.x,-p.z):shape.moveTo(p.x,-p.z));shape.closePath();
 for(const hole of polygon.slice(1)){const path=new T.Path();hole.map(p=>mapPoint(p)).forEach((p,i)=>i?path.lineTo(p.x,-p.z):path.moveTo(p.x,-p.z));shape.holes.push(path);}
 const land=mesh(new T.ExtrudeGeometry(shape,{depth:.65,bevelEnabled:true,bevelThickness:.08,bevelSize:.12,bevelSegments:2,steps:1}),new T.MeshPhysicalMaterial({color:0x3b505b,metalness:.9,roughness:.34,envMapIntensity:.7}),mapRoot,[0,-.82,0]);land.rotation.x=-Math.PI/2;
 line([...outer,outer[0]].map(p=>V(p.x,.015,p.z)),0x237488,mapRoot,.7);
}
const mapRoads=[];
for(const coords of GEO.roads){const points=coords.map(p=>mapPoint(p,.025));mapRoads.push(line(points,0x264959,mapRoot,.55));}
const mapRoutes=GEO.routes.map((coords,i)=>{
 const points=coords.map(p=>mapPoint(p,.25+i*.06)),curve=new T.CatmullRomCurve3(points);
 const geometry=new T.TubeGeometry(curve,points.length*3,.13,5,false),route=new T.Mesh(geometry,new T.MeshBasicMaterial({color:new T.Color(.25,2.2,2.8)}));route.geometry.setDrawRange(0,0);mapRoot.add(route);return{mesh:route,points,curve,total:geometry.index.count};
});
const markers=[];
for(const n of GEO.nodes){const p=mapPoint([n.lon,n.lat],.25),isWarehouse=n.role!=='customer';
 const mark=mesh(isWarehouse?new T.BoxGeometry(1.0,1.8,1.0):new T.CylinderGeometry(.38,.38,1.1,20),isWarehouse?cyan:white,mapRoot,[p.x,isWarehouse?1:.65,p.z]);markers.push(mark);
 if(['W-WESTGATE','D-NORTHPOINT','D-HOUGANG'].includes(n.facility_id)){const label=labelSprite(n.facility_id==='W-WESTGATE'?'Westgate':n.facility_id==='D-HOUGANG'?'Hougang':'Northpoint');label.scale.multiplyScalar(1.7);label.position.set(p.x,3.1,p.z);mapRoot.add(label);}
}
function insideLand(x,z){return landRings.some(ring=>{let hit=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){
 const a=mapPoint(ring[i]),b=mapPoint(ring[j]);if((a.z>z)!==(b.z>z)&&x<(b.x-a.x)*(z-a.z)/(b.z-a.z)+a.x)hit=!hit;
}return hit;});}
const mapBuildings=new T.InstancedMesh(new T.BoxGeometry(1,1,1),new T.MeshPhysicalMaterial({color:0x1b2a33,metalness:.97,roughness:.25,envMapIntensity:.5}),900);
let attempt=0;for(let i=0;i<900;i++){let x,z;do{x=(seeded(attempt+700)-.5)*200;z=(seeded(attempt+1700)-.5)*116;attempt++;}while(!insideLand(x,z)&&attempt<100000);
 const h=.6+seeded(i+2700)*5.6;transform.position.set(x,h/2-.1,z);transform.scale.set(.5+seeded(i+99)*1.2,h,.6+seeded(i+149)*1.5);transform.rotation.y=0;transform.updateMatrix();mapBuildings.setMatrixAt(i,transform.matrix);}mapRoot.add(mapBuildings);
const hub=new T.Group();hub.position.set(0,5,0);mapRoot.add(hub);mesh(new T.IcosahedronGeometry(1.6,1),metal,hub);const hubRing=torus(2.5,.05,cyan,hub);hubRing.rotation.x=Math.PI/2;
const mapPulses=mapRoutes.map(r=>({mesh:mesh(new T.SphereGeometry(.35,16,12),cyan,mapRoot),curve:r.curve}));

function cameraAt(position,target,fov=43){camera.position.copy(position);camera.lookAt(target);camera.fov=fov;camera.near=position.distanceTo(target)<1?.005:.1;camera.updateProjectionMatrix();}
function localReveal(u,start=0,length=1){return ease((u-start)/length);}
function pose(t){
 const shot=shotAt(t),i=FILM.scenes.indexOf(shot),u=t-shot.start;worlds.forEach((g,j)=>g.visible=i===j);
 scene.fog.density=i===0?.027:i===1?.023:i===2?.009:0;scene.fog.color.setHex(i===2?0x07111b:0x061019);
 scene.background.setHex(i===3?0x000000:0x02070b);renderer.toneMappingExposure=i===0?.78:i===3?.75:i===5?1.05:.82;
 scene.environmentIntensity=i===5?.75:.45;key.intensity=i===5?2.2:1.3;
 bloom.strength=i===3?.32:i===5?.24:.2;warning.intensity=0;rim.intensity=i===3?15:40;
 blur.uniforms.amount.value=0;blur.uniforms.radial.value=1;
 if(i===0){
  warning.position.set(.1,1.5,.3);
  const pull=localReveal(u,6.3,1.25),macro=V(.235+Math.sin(u*.22)*.025,1.36,.235),wide=V(.3,3.3,8.3);
  cameraAt(macro.lerp(wide,pull),V(0,1.27,-.1),mix(30,44,pull));
  const sweep=Math.sin(u*.95);laser.position.y=.03+sweep*.085;laserGlow.position.y=laser.position.y;laser.visible=u>2;laserGlow.visible=u>2;
  warning.intensity=u>2?.025+.015*Math.sin(u*4):0;
  blur.uniforms.amount.value=Math.exp(-Math.pow((u-6.9)/.4,2))*.07;
 }else if(i===1){
  const z=mix(8,-27,Math.pow(u/20,1.35));cameraAt(V(.55+Math.sin(u*.3)*.28,1.55+Math.sin(u*.2)*.2,z),V(-.3,1.55,z-8),47);
  warning.position.set(-1.2,1.8,z-2);warning.intensity=3+2*Math.sin(u*3);
  leds.forEach((o,j)=>{o.material=(Math.sin(u*2+j*.6)>.5)?red:cyan;});
  for(let k=0;k<sparkCount;k++){
   const age=(u*.7+seeded(k+300))%1;const x=-1.25+seeded(k+500)*.2,y=1.7+seeded(k+600)*1.2,zp=z-2-seeded(k+700)*8;
   const dx=(seeded(k+800)-.3)*age*2,dy=-age*age*1.7;const q=k*6;
   sparkPositions.set([x+dx,y+dy,zp,x+dx-.05,y+dy+.06,zp-.12],q);
  }sparkGeo.attributes.position.needsUpdate=true;
  blur.uniforms.amount.value=.004+Math.pow(u/20,5)*.025;
 }else if(i===2){
  const p=(u*.014+.02)%1,point=drive.getPointAt(p),direction=drive.getTangentAt(p);van.position.copy(point);van.rotation.y=Math.atan2(direction.x,direction.z);wheels.forEach(o=>o.rotation.x=u*7);
  const sideways=V(direction.z,0,-direction.x).multiplyScalar(.75);
  const overhead=point.clone().add(V(1,75,3)),follow=point.clone().add(direction.clone().multiplyScalar(-7)).add(sideways).add(V(0,2.8,0));
  let pos;if(u<7.5)pos=overhead;else if(u<8.6)pos=overhead.lerp(follow,localReveal(u,7.5,1.1));else if(u<27)pos=follow;else{const a=(u-27)*.2;pos=point.clone().add(V(Math.sin(a)*14,35+Math.sin(u*.17)*2,Math.cos(a)*14));}
  cameraAt(pos,point.clone().add(V(0,.9,0)),u<7.5?42:49);
  for(let k=0;k<rainCount;k++){
   const x=point.x+(seeded(k+4000)-.5)*50,z=point.z+(seeded(k+8000)-.5)*50,y=((seeded(k+12000)*30-u*17)%30+30)%30;
   rainArray.set([x,y,z,x-.15,y+1.4,z-.22],k*6);
  }rainGeometry.attributes.position.needsUpdate=true;
  blur.uniforms.amount.value=Math.exp(-Math.pow((u-8.05)/.35,2))*.08+.002;
 }else if(i===3){
  const ignition=localReveal(u,.4,1.5);core.scale.setScalar(.5+.5*ignition);core.rotation.set(u*.11,u*.32,Math.sin(u*.17)*.1);
  coreRings.forEach((o,j)=>{o.rotation.y=u*(.25+j*.12);o.rotation.z=u*.08+j;});
  cameraAt(V(Math.sin(u*.13)*.7,.55, mix(12,6.5,localReveal(u,.1,1.4))),V(0,0,0),40);
  bloom.strength=.2+ignition*.18;coreWorld.visible=ignition>.005;blur.uniforms.amount.value=Math.exp(-Math.pow((u-.8)/.45,2))*.065;
 }else if(i===4){
  const grow=localReveal(u,.1,4);algorithm.rotation.y=Math.sin(u*.1)*.17;
  networkNodes.forEach((o,j)=>o.scale.setScalar(Math.max(.001,localReveal(u,j*.32,.7))));
  networkEdges.forEach((e,j)=>{e.mesh.scale.setScalar(Math.max(.001,localReveal(u,j*.13,1)));});
  pulses.forEach(o=>o.mesh.position.copy(o.curve.getPointAt((u*.18+o.index*.13)%1)));
  cameraAt(V(Math.sin(u*.13)*1.7,.7+Math.cos(u*.16)*.8,13.0-1.0*grow),V(Math.sin(u*.13),.1,0),43);
 }else{
  const a=-.8+Math.PI*clamp(u/35),r=153;cameraAt(V(Math.sin(a)*r,100-Math.sin(u*.09)*12,Math.cos(a)*r),V(0,2,0),43);
  hub.rotation.y=u*.24;hubRing.rotation.z=u*.2;
  mapRoutes.forEach((r,j)=>{const count=Math.floor(r.total*localReveal(u,2+j*1.2,5));r.mesh.geometry.setDrawRange(0,count);});
  mapPulses.forEach((o,j)=>o.mesh.position.copy(o.curve.getPointAt((u*.08+j*.23)%1)));
 }
 return{shot,u,index:i};
}

let current=0,playing=false,last=0,rendering=false;
const textBoxes=[];
function drawText(text,x,y,size=26,{align='left',alpha=1,color='#f0f6fa',weight=400}={}){
 ink.save();ink.globalAlpha=alpha;ink.font=`${weight} ${size}px Arial`;ink.fillStyle=color;ink.textAlign=align;
 const m=ink.measureText(text);textBoxes.push({text,x:x-(align==='center'?m.width/2:align==='right'?m.width:0),y:y-size,w:m.width,h:size*1.15});ink.fillText(text,x,y);ink.restore();
}
function drawOverlay(t,state){
 textBoxes.length=0;const {shot,u,index}=state;
 const shade=ink.createLinearGradient(0,690,0,H);shade.addColorStop(0,'rgba(0,0,0,0)');shade.addColorStop(1,'rgba(0,0,0,.96)');ink.fillStyle=shade;ink.fillRect(0,690,W,390);
 ink.fillStyle='rgba(0,0,0,.85)';ink.fillRect(0,0,W,65);
 drawText(index<3?'COLD CHAIN / A CONCEPT FILM':'PHARMACOLDOPS',78,42,18,{color:'#c4d7df'});
 drawText(shot.part,W-78,42,17,{align:'right',color:index<3?'#d9a0a6':'#8ce7f8'});
 const show=index===0?8:index===3?3:2;const opacity=localReveal(u,show,.9)*(1-localReveal(u,shot.end-shot.start-1.5,1));
 drawText(shot.title,index===3?W/2:95,852,index===3?78:49,{align:index===3?'center':'left',weight:index===3?600:400,alpha:opacity});
 const note=noteAt(t);ink.font='26px Arial';let line='',lines=[];for(const word of note.split(' ')){const next=line?line+' '+word:word;if(ink.measureText(next).width>1700){lines.push(line);line=word;}else line=next;}if(line)lines.push(line);
 lines.forEach((s,i)=>drawText(s,960,969+i*34,26,{align:'center',color:'#d8e5ec'}));
 drawText(index===5?'CONCEPT VISUALS / SIMULATED OPERATIONS / MAP: OPENSTREETMAP CONTRIBUTORS + NATURAL EARTH':'CONCEPT VISUALS / SIMULATED OPERATIONS',960,1050,16,{align:'center',color:'#8c9fae'});
 // Controlled black transitions; no full-screen flashing warning strobes.
 const edge=Math.min(localReveal(u,0,.28),1-localReveal(u,shot.end-shot.start-.35,.35));
 if(edge<1){ink.fillStyle=`rgba(0,0,0,${1-edge})`;ink.fillRect(0,65,W,860);}
}
window.seek=function(t,{quiet=false}={}){
 current=clamp(Number(t),0,149.999);const s=pose(current);composer.render();ink.globalAlpha=1;ink.drawImage(renderer.domElement,0,0,W,H);drawOverlay(current,s);
 if(!quiet){document.getElementById('time').value=current;document.getElementById('clock').textContent=`${current.toFixed(1)} / 150 s`;status.textContent=noteAt(current);}
 return{time:current,scene:s.shot.id,camera:camera.position.toArray(),textBounds:[...textBoxes],webgl:true};
};
document.getElementById('time').addEventListener('input',e=>{playing=false;document.getElementById('play').textContent='Play';window.seek(e.target.value);});
document.getElementById('play').addEventListener('click',()=>{if(rendering)return;playing=!playing;last=0;document.getElementById('play').textContent=playing?'Pause':'Play';if(playing)requestAnimationFrame(tick);});
function tick(now){if(!playing)return;if(last)current+=(now-last)/1000;last=now;if(current>=150){current=0;playing=false;document.getElementById('play').textContent='Play';}window.seek(current);if(playing)requestAnimationFrame(tick);}

window.renderMovie=async function({fps=30,start=0,end=10}={}){
 if(rendering)throw Error('render already active');if(fps!==30||start%10!==0||end!==start+10||start<0||end>150)throw Error('encode one exact ten-second segment at 30fps');
 rendering=true;playing=false;const session=await fetch('./render-session.json').then(r=>r.json());
 const config={codec:'avc1.640028',width:W,height:H,bitrate:8_000_000,framerate:fps,hardwareAcceleration:'prefer-hardware',avc:{format:'avc'}};
 const supported=await VideoEncoder.isConfigSupported(config);if(!supported.supported)throw Error('H.264 WebCodecs unavailable');
 const target=new ArrayBufferTarget(),muxer=new Muxer({target,video:{codec:'avc',width:W,height:H,frameRate:fps},fastStart:'in-memory',firstTimestampBehavior:'offset'});
 let failure=null;const encoder=new VideoEncoder({output:(chunk,meta)=>muxer.addVideoChunk(chunk,meta),error:error=>{failure=error;}});encoder.configure(config);
 window.renderProgress={status:'rendering',frame:0,total:(end-start)*fps,start,end};
 try{
  for(let i=0;i<(end-start)*fps;i++){
   if(failure)throw failure;window.seek(start+i/fps,{quiet:true});
   const frame=new VideoFrame(out,{timestamp:Math.round(i*1e6/fps),duration:Math.round(1e6/fps)});encoder.encode(frame,{keyFrame:i%(fps*2)===0});frame.close();
   while(encoder.encodeQueueSize>3){await new Promise(resolve=>setTimeout(resolve,2));if(failure)throw failure;}
   if(i%10===0){window.renderProgress={status:'rendering',frame:i,total:(end-start)*fps,start,end,time:start+i/fps,scene:shotAt(start+i/fps).id};await new Promise(resolve=>setTimeout(resolve,0));}
  }
  await encoder.flush();encoder.close();muxer.finalize();
  const response=await fetch(session.upload,{method:'POST',headers:{'Content-Type':'video/mp4','X-Render-Session':session.token,'X-Render-Part':String(start/10)},body:new Blob([target.buffer],{type:'video/mp4'})});if(!response.ok)throw Error('render upload failed '+response.status);
  window.renderProgress={status:'saved',frame:(end-start)*fps,total:(end-start)*fps,start,end,bytes:target.buffer.byteLength};return window.renderProgress;
 }catch(error){window.renderProgress={status:'failed',error:String(error)};throw error;}
 finally{rendering=false;}
};
await document.fonts.ready;window.seek(0);window.cinematicReady=true;
window.capabilities={webgl2:renderer.capabilities.isWebGL2,videoEncoder:typeof VideoEncoder!=='undefined',revision:T.REVISION,threeDScenes:6};
