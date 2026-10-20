// An English, code-drawn explainer. Illustrations are not live system events.
export const STORY = {
  title: 'Beyond the temperature alarm', duration: 90, width: 1920, height: 1080,
  sourceApplicationCommit: 'ff4dcb8', snapshotDate: '2026-10-20',
  prototype: { productId: 'vaccine_2_8', minC: 2, maxC: 8, allowableMin: 30, mktCeilingC: 10 },
  observation: { endMin: 120, intervals: [[0,15,5],[15,105,20],[105,120,5]], hotMin: 90, hotMktC: 20 },
  routeBenchmark: { greedyKm: 165.26, optimizedKm: 137.85, vehicles: 3, solverRuns: 49 },
  parking: { warehouseChoices: 5, receivingHospitals: 14, selected: ['D-NORTHPOINT','D-HOUGANG'] },
  sources: [
    'src/rule_engine/rules_config.json', 'frontend-vue/src/lib/engine.js',
    'docs/M2温度序列与MKT.md', 'docs/人工审核与有效处置.md',
    'docs/独立加急与仓库停车规则.md', 'docs/知识图谱可靠性与恢复.md',
    'docs/案例审计报告导出.md', 'docs/M5正式评估.md', 'docs/FINAL_REPORT_EN.md'
  ],
  scenes: [
    {id:'alarm',start:0,end:6,title:'An alarm is only the beginning.',tag:'01 / THE PROBLEM',
      notes:['A cold-chain temperature alarm raises three questions: quality, supply and evidence.'],scope:'SIMULATED DATA / NO REAL MEDICINE BATCH'},
    {id:'exposure',start:6,end:18,title:'First, reconstruct the exposure.',tag:'02 / THE OBSERVATION',
      notes:['A sequence tells us how hot, for how long, and which readings are actually known.',
             'Here, a simulated 90-minute hot window has a window MKT of 20.0 C.'],scope:'ILLUSTRATIVE CONSTANT INTERVALS / PROTOTYPE STORAGE BAND'},
    {id:'rules',start:18,end:30,title:'Make the rule inspectable.',tag:'03 / THE REASONING',
      notes:['The prototype can show exactly which rule fired. Its numerical limits are engineering assumptions.',
             'Model candidates are advisory. They cannot authorise medicine disposition.'],scope:'PROTOTYPE RULE EXAMPLE / NOT PRODUCT-STABILITY VALIDATION'},
    {id:'review',start:30,end:40,title:'Separate advice from authority.',tag:'04 / THE HUMAN GATE',
      notes:['Pending review blocks the linked actions. The original recommendation remains unchanged.',
             'A separate recorded review outcome can govern subsequent delivery.'],scope:'WORKFLOW ILLUSTRATION / NOT AN ACTUAL HUMAN REVIEW'},
    {id:'routes',start:40,end:54,title:'Replan without erasing reality.',tag:'05 / THE DELIVERY',
      notes:['Replacement work must respect delivery windows, temperature zones and available vehicles.',
             'Preview, explicit adoption and simulated delivery are different states.'],scope:'SCHEMATIC ROUTE ILLUSTRATION / NOT A SOLVER REPLAY OR GPS'},
    {id:'parking',start:54,end:62,title:'The day must end at a warehouse.',tag:'06 / THE BOUNDARY',
      notes:['Users choose the permitted subset of five warehouses.',
             'Hospitals receive deliveries. They are not day-end parking terminals.'],scope:'14 RECEIVING HOSPITALS / 5 WAREHOUSE CHOICES'},
    {id:'evidence',start:62,end:72,title:'Keep a trail you can inspect.',tag:'07 / THE EVIDENCE',
      notes:['The case store preserves original records, review outcomes and delivery state.',
             'The graph mirrors original case evidence. The audit joins both; graph answers do not replace review history.'],scope:'ILLUSTRATIVE DATA FLOW / SOURCES ARE NOT COMPLIANCE CERTIFICATES'},
    {id:'benchmark',start:72,end:82,title:'Measure the claim. Keep the limits.',tag:'08 / THE EXPERIMENT',
      notes:['On one frozen Singapore static instance, both plans use three vehicles.',
             '165.26 to 137.85 km is a 16.59% distance reduction, not measured operating savings.'],scope:'FROZEN STATIC INSTANCE / 49 SOLVER RUNS IN THE FULL STUDY'},
    {id:'close',start:82,end:90,title:'PharmaColdOps',tag:'09 / THE PRINCIPLE',
      notes:['Explain the decision. Preserve the evidence. Respect the constraints.',
             'Simulated data. Engineering limits. Advisory models. People retain responsibility.'],scope:'PROTOTYPE / CLINICAL VALIDITY AND INDEPENDENT QA QUALITY NOT ESTABLISHED'}
  ]
};

export function sceneAt(time) {
  const t = Math.max(0, Math.min(STORY.duration - 1e-6, time));
  return STORY.scenes.find(s => t >= s.start && t < s.end);
}
export function noteAt(time) {
  const scene = sceneAt(time), n = Math.min(scene.notes.length-1, Math.floor((time-scene.start)/(scene.end-scene.start)*scene.notes.length));
  return scene.notes[Math.max(0,n)];
}
