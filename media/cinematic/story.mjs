export const FILM={
 title:'PharmaColdOps - From disruption to a traceable response',duration:150,width:1920,height:1080,fps:30,
 language:'en',sourceApplicationCommit:'182e0d6',
 scenes:[
  {id:'valve',start:0,end:15,part:'BUSINESS PAIN',title:'One excursion. More than one consequence.',
   notes:['A temperature alarm is the beginning of a decision, not the end of one.',
          'Quality, supply and accountability are suddenly connected.'],reference:'Metal cooling valve; red warning sweep; macro-to-warehouse whip pullback.'},
  {id:'data',start:15,end:35,part:'BUSINESS PAIN',title:'Disconnected data compounds the delay.',
   notes:['A reading, an order and a route can tell different parts of the same story.',
          'Without an inspectable handover, the next action remains uncertain.'],reference:'Macro server-aisle flyby; translucent data grid; sparks and accelerated forward move.'},
  {id:'city',start:35,end:75,part:'BUSINESS PAIN',title:'A disruption travels through the network.',
   notes:['Delivery windows keep moving while quality staff reconstruct the exposure.',
          'Temperature zones and available vehicles still constrain the response.',
          'Completed work cannot simply disappear when the plan changes.',
          'Weather and infrastructure shown here are conceptual imagery, not integrated live feeds.'],reference:'Overhead dark digital city; rain; rapid plunge to a sleek black delivery vehicle.'},
  {id:'core',start:75,end:95,part:'VALUE PROPOSITION',title:'PharmaColdOps',
   notes:['Connect the observation, the explanation and the next delivery action.',
          'Inspectable recommendations. Separate human review. Explicit execution.'],reference:'Black-screen push; rotating metallic core; cyan strip-light ignition.'},
  {id:'network',start:95,end:115,part:'VALUE PROPOSITION',title:'One connected, inspectable handover.',
   notes:['Preserve the original advice and record the effective human outcome separately.',
          'Model candidates remain advisory. Evidence is inspectable, not a medicine certificate.'],reference:'Expanding algorithmic node network; blue-white pulses; organic following pan.'},
  {id:'singapore',start:115,end:150,part:'VALUE PROPOSITION',title:'A Singapore network. A traceable response.',
   notes:['Compare feasible delivery options under the same operational constraints.',
          'A preview does not move a vehicle. Adoption and delivered state are different.',
          'End the day only at a user-permitted warehouse, never at a hospital.',
          'Simulated operations. Engineering thresholds. Human responsibility.'],reference:'Brushed-metal Singapore facility network; cyan route reveals; full 180-degree hub orbit.'}
 ],
 scope:'Procedural 3D concept film. No live incidents, real fleet, weather integration, solver replay, clinical validation or Apple/RED affiliation is claimed.',
 cameraReference:'8K/RED wording is a visual reference only; actual delivery is 1920x1080 at 30fps.',
 speech:false,kling:false
};
export const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
export const ease=x=>{x=clamp(x);return x*x*(3-2*x);};
export const mix=(a,b,t)=>a+(b-a)*t;
export function shotAt(t){return FILM.scenes.find(s=>t>=s.start&&t<s.end)||FILM.scenes[t<0?0:5];}
export function noteAt(t){const s=shotAt(t);return s.notes[Math.min(s.notes.length-1,Math.max(0,Math.floor((t-s.start)/(s.end-s.start)*s.notes.length)))];}
