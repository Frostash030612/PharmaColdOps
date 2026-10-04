"""Blind human M6 evaluation workflow. Never manufacture human gold.

prepare: real isolated API snapshots, hidden routing predictions, blank two-rater
templates, source references and latencies. score: explicit human labels with
packet hashes; disagreement requires independent adjudication.
"""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import evaluate_qa as contract
from api import service
from api.schemas import QAIn
from knowledge_graph.build_graph import REGULATIONS,SOPS
from optimisation.case_repository import read_case_originals

INTENTS=['why_disposition','audit_chain','product_requirements','cause_context','disposition_stats','unsupported']
RATINGS=['answer_correctness','evidence_relevance','evidence_sufficiency','refusal_appropriate','unsupported_claims']


def sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def csv_write(path,fields,rows):
    with path.open('w',encoding='utf-8',newline='')as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def questions():
    with(ROOT/'data/qa/intent_labels.csv').open(encoding='utf-8-sig',newline='')as f:legacy=list(csv.DictReader(f))
    rows=[{'question':r['question'],'lang':r['lang'],'origin':'legacy FAQ keyword, not independently sampled user utterance',
           'scenario_id':'S017','product_id':'vaccine_2_8'}for r in legacy]
    # Explicitly authored test stimuli, not human target labels or natural
    # user-population samples. Covers existing live router and unsupported scope.
    stimuli=[
      ('zh','为什么这个案例需要这样的处置？','S017'),('en','Why was this case assigned this disposition?','S017'),
      ('zh','请展示这次异常的全过程链路。','S001'),('en','Show the audit chain for this case.','S001'),
      ('zh','该产品的储存要求和允许时长是什么？','S001'),('en','What are the product storage requirements?','S001'),
      ('zh','这个根因最常见于哪些运输阶段？','S017'),('en','In which stages is this cause most common?','S017'),
      ('zh','请统计已登记案例的处置分布。','S001'),('en','Show disposition stats for recorded cases.','S001'),
      ('zh','今天的天气好吗？','S001'),('en','What will the weather be tomorrow?','S001'),
      ('zh','能否确认这支具体品牌疫苗的真实效价？','S001'),('en','Certify actual potency of this specific vaccine brand.','S001'),
      ('zh','为什么这个不存在的案例被判报废？','missing'),('en','Why was this nonexistent case scrapped?','missing'),
    ]
    rows += [{'question':q,'lang':lang,'scenario_id':sid,'product_id':'vaccine_2_8','origin':'authored evaluation stimulus, no gold assigned'}for lang,q,sid in stimuli]
    random.Random(42).shuffle(rows)
    return [{'question_id':f'Q{i:03d}',**r}for i,r in enumerate(rows,1)]


def predictions(rows):
    result=subprocess.run(['node',str(ROOT/'scripts/predict_qa_intents.mjs')],input=json.dumps(rows,ensure_ascii=False),text=True,capture_output=True,check=True)
    values=json.loads(result.stdout)
    if {v['question_id']for v in values}!={r['question_id']for r in rows}:raise ValueError('router identities differ')
    return {v['question_id']:v for v in values}


def prepare(output):
    if output.exists():raise ValueError('fresh packet directory required')
    output.mkdir(parents=True)
    inputs=questions();routed=predictions(inputs);prefix='RQABLINDEVAL-'+uuid.uuid4().hex+'-'
    graph={};args=SimpleNamespace(configured_test_graph=False,image=None,keep=False,limit=None)
    snapshots=[];contract_report={};cleanup={'status':'not_started'}
    with contract._store(output,prefix):
        with contract._graph(args,graph)as driver:
            try:
                contract_report=contract._evaluate(args,prefix)
                dump(output/'derived-contract-report.json',contract_report)
                if contract_report['checks_failed']:
                    raise RuntimeError('derived contract checks failed; preserve report, do not release a successful packet')
                mapping={r['scenario_id']:r['run_id']for r in contract_report['created_cases']}
                for q in inputs:
                    predicted=routed[q['question_id']];intent=predicted['predicted_intent']
                    case_id=mapping.get(q['scenario_id'],'UNKNOWN-BLIND-EVAL')
                    body={'question_type':intent}
                    if intent in ['why_disposition','audit_chain','cause_context']:body['run_id']=case_id
                    if intent=='product_requirements':body['product_id']=q['product_id']
                    start=time.perf_counter()
                    if intent=='unsupported':response={'status':'concept_fallback','answer':predicted['fallback'],'evidence':[]};source='actual_client_fallback'
                    else:response=service.qa_view(QAIn(**body));source='actual_service_query'
                    latency=time.perf_counter()-start
                    original=service.find_run(case_id)
                    facts={k:original.get(k)for k in ['run_id','event','spec','disposition','rule_no','reason','review_required','review_reasons']}if original else {'case_exists':False}
                    entry={**q,'predicted_intent':intent,'source':source,'response':response,'case_facts':facts,
                           'latency_seconds':latency,'measurement_scope':'service/local-fallback call; not HTTP/browser/network latency'}
                    entry['response_sha256']=sha({'question':q,'response':response,'case_facts':facts})
                    snapshots.append(entry)
            finally:
                originals,_=read_case_originals(output/'cases.sqlite3',legacy_file=output/'runs.jsonl')
                dump(output/'cases.manifest.json',originals)
                cleanup=contract._cleanup(driver,output,prefix)
    manifest={'schema':'m6-blind-packet-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'questions':inputs,'responses':snapshots,'source_hashes':{str(p.relative_to(ROOT)):file_sha(p)for p in [
            ROOT/'frontend-vue/src/lib/qa.js',ROOT/'frontend-vue/src/i18n/zh.js',ROOT/'frontend-vue/src/i18n/en.js',
            ROOT/'scripts/predict_qa_intents.mjs',ROOT/'scripts/evaluate_qa.py',ROOT/'src/knowledge_graph/qa.py',
            ROOT/'src/knowledge_graph/build_graph.py',ROOT/'src/api/service.py',ROOT/'src/api/schemas.py',
            ROOT/'data/qa/intent_labels.csv',ROOT/'src/rule_engine/rules_config.json',Path(__file__)]},
        'graph':graph,'cleanup':cleanup,'human_gold_available':False,'routing_is_keywords_not_NLP':True,
        'annotation_stage_order':'seal intent labels first without responses; then answer/evidence assessment',
        'limitations':['legacy words derived from FAQ','additional prompts authored by evaluation developer','not natural user-population accuracy','rater identities self-declared not authenticated']}
    packet_sha=sha(manifest);manifest['packet_sha256']=packet_sha
    dump(output/'predictions.private.json',manifest)
    dump(output/'derived-contract-report.json',contract_report)
    dump(output/'reference-sources.json',{'regulations':REGULATIONS,'sops':SOPS,'rules_config':json.loads(contract.CONFIG.read_text(encoding='utf-8')),
        'scope':'all current references, not model expected citations; engineering defaults are not validated manufacturer stability limits'})
    blind=output/'blind-intent';blind.mkdir()
    blinded=[{'question_id':q['question_id'],'question':q['question'],'lang':q['lang'],'packet_sha256':packet_sha}for q in inputs]
    csv_write(blind/'questions.csv',list(blinded[0]),blinded)
    annotation=[{**q,'annotator_id':'','expected_intent':'','acceptable_intents':'','note':''}for q in blinded]
    for rater in ['A','B']:csv_write(blind/f'intent-{rater}.csv',list(annotation[0]),annotation)
    answer_dir=output/'answer-review';answer_dir.mkdir()
    dump(answer_dir/'responses.json',[{k:v for k,v in r.items()if k not in ['predicted_intent','source','latency_seconds','origin']}for r in snapshots])
    ratings=[{'question_id':r['question_id'],'packet_sha256':packet_sha,'response_sha256':r['response_sha256'],'annotator_id':'',
              **{k:''for k in RATINGS},'relevant_evidence_ids':'','checked_source_urls':'','note':''}for r in snapshots]
    for rater in ['A','B']:csv_write(answer_dir/f'ratings-{rater}.csv',list(ratings[0]),ratings)
    adjudication=[{'question_id':r['question_id'],'packet_sha256':packet_sha,'adjudicator_id':'','expected_intent':'','note':''}for r in snapshots]
    csv_write(output/'adjudication-template.csv',list(adjudication[0]),adjudication)
    live=[r['latency_seconds']for r in snapshots if r['source']=='actual_service_query']
    report={'status':'awaiting_human_annotations','independent_intent_accuracy':None,'independent_answer_accuracy':None,
        'packet_sha256':packet_sha,'questions':len(inputs),'live_queries':len(live),
        'service_latency_seconds':{'median':float(__import__('numpy').median(live)),'p95':float(__import__('numpy').percentile(live,95))},
        'latency_scope':'measured call only, not HTTP end-to-end or production SLA','derived_checks_passed':contract_report['checks_run']-contract_report['checks_failed'],
        'cleanup':cleanup,'annotation_identity':'self-declared human, cannot be authenticated by scorer'}
    dump(output/'pending-report.json',report)
    (output/'INSTRUCTIONS.md').write_text('''# Blind human review

1. Give A and B only blind-intent/ and this scoring protocol. Do not show responses,
   prediction keywords, private model outputs or each other's labels before submission.
2. Labels: why_disposition, audit_chain, product_requirements, cause_context,
   disposition_stats, unsupported. ambiguous is allowed only with semicolon-separated
   acceptable_intents. Do not force bare keywords into an unsupported interpretation.
   Label by intended task, not by matching routing keywords:
   why_disposition = a specific case's disposition reason and supporting evidence;
   audit_chain = that case's event/decision/reshipment trace;
   product_requirements = product storage limits and allowed excursion duration;
   cause_context = patterns of stages/products for a case's recorded cause;
   disposition_stats = aggregate counts/distribution of recorded dispositions;
   unsupported = outside these tasks, including weather or actual clinical potency
   certification. A missing case is still an in-scope intent; assess no_case in phase 2.
3. Seal both intent CSVs. Then give answer-review/responses.json and reference-sources.json.
4. Ratings: correctness/relevance/sufficiency 0=wrong, 1=partial, 2=adequate; refusal
   0=wrong,1=appropriate,NA=not applicable; unsupported_claims 0=none,1=present.
   Sufficiency/relevance may be NA only when evidence is not required. Record the actual
   source URLs consulted; links alone do not prove specific stability numbers.
5. Each file must have a nonempty, consistent annotator_id. Reviewers must be distinct.
   Self-declaration is not identity verification. Do not use model outputs as human gold.
6. Intent disagreements require a separate adjudication CSV with rationale, not majority
   copied from the program. Preserve packet/response hashes. Re-running creates new IDs.
7. Score only after complete annotation. Until then accuracy is unavailable, not zero or 100%.
''',encoding='utf-8')
    return report


def read_annotations(path,manifest,kind):
    with Path(path).open(encoding='utf-8-sig',newline='')as f:rows=list(csv.DictReader(f))
    expected={q['question_id']for q in manifest['questions']};result={}
    for r in rows:
        qid=r.get('question_id')
        if qid not in expected or qid in result:raise ValueError('unknown or duplicate annotation identity')
        if r.get('packet_sha256')!=manifest['packet_sha256']:raise ValueError('annotation belongs to a different response packet')
        actor=r.get('annotator_id','').strip()
        if not actor:raise ValueError('human annotator identity missing')
        r['annotator_id']=actor
        if kind=='intent':
            value=r.get('expected_intent','').strip()
            if value not in INTENTS+['ambiguous']:raise ValueError('unlabelled or invalid intent; cannot score independence')
            accepted=set(filter(None,r.get('acceptable_intents','').split(';')))
            if value=='ambiguous'and(not accepted or not accepted<=set(INTENTS)):raise ValueError('ambiguous input requires explicit acceptable intent set')
        else:
            source=next(s for s in manifest['responses']if s['question_id']==qid)
            if r.get('response_sha256')!=source['response_sha256']:raise ValueError('response content changed')
            for key in RATINGS:
                allowed={'0','1'}if key in ['refusal_appropriate','unsupported_claims']else{'0','1','2'}
                if key in ['refusal_appropriate','evidence_relevance','evidence_sufficiency']:allowed.add('NA')
                if r.get(key)not in allowed:raise ValueError('incomplete or invalid human quality rating')
            if not r.get('checked_source_urls','').strip():raise ValueError('human source review provenance missing')
        result[qid]=r
    if set(result)!=expected:raise ValueError('all packet rows must be annotated; no selective denominator')
    if len({r['annotator_id']for r in result.values()})!=1:raise ValueError('one consistent reviewer per file required')
    return result


def score(packet,intent_a,intent_b,ratings_a,ratings_b,adjudication=None):
    import numpy as np
    from sklearn.metrics import accuracy_score,classification_report,cohen_kappa_score,confusion_matrix
    manifest=json.loads(Path(packet).read_text(encoding='utf-8'));saved=manifest.pop('packet_sha256')
    if sha(manifest)!=saved:raise ValueError('packet contents changed')
    if manifest.get('schema')!='m6-blind-packet-v1':raise ValueError('unsupported packet schema')
    question_ids=[q['question_id']for q in manifest['questions']]
    response_ids=[r['question_id']for r in manifest['responses']]
    if len(question_ids)!=len(set(question_ids))or len(response_ids)!=len(set(response_ids))or set(question_ids)!=set(response_ids):raise ValueError('packet question/response identities differ')
    manifest['packet_sha256']=saved
    a=read_annotations(intent_a,manifest,'intent');b=read_annotations(intent_b,manifest,'intent')
    ra=read_annotations(ratings_a,manifest,'ratings');rb=read_annotations(ratings_b,manifest,'ratings')
    actor=lambda labels:next(iter(labels.values()))['annotator_id']
    if actor(a)==actor(b)or actor(ra)==actor(rb):raise ValueError('independent reviewers must differ')
    if actor(a)!=actor(ra)or actor(b)!=actor(rb):raise ValueError('phase reviewer identities must agree')
    conflicts=[qid for qid in a if(a[qid]['expected_intent'],a[qid].get('acceptable_intents',''))!=(b[qid]['expected_intent'],b[qid].get('acceptable_intents',''))]
    decided={}
    if conflicts:
        if adjudication is None:raise ValueError('independent intent disagreements require human adjudication')
        with Path(adjudication).open(encoding='utf-8-sig',newline='')as f:
            for r in csv.DictReader(f):
                if r['question_id']not in conflicts:continue
                if r.get('packet_sha256')!=saved or r['question_id']in decided or not r.get('adjudicator_id','').strip()or not r.get('note','').strip():raise ValueError('invalid adjudication provenance')
                if r['adjudicator_id'].strip()in [actor(a),actor(b)]:raise ValueError('adjudication requires a distinct reviewer identity')
                if r['expected_intent']not in INTENTS:raise ValueError('adjudication requires one supported final label')
                decided[r['question_id']]=r['expected_intent']
        if set(decided)!=set(conflicts):raise ValueError('not all disagreements adjudicated')
    truth=[];pred=[];ambiguous=0
    for r in manifest['responses']:
        qid=r['question_id'];label=decided.get(qid,a[qid]['expected_intent'])
        if label=='ambiguous':ambiguous+=1;continue
        truth.append(label);pred.append(r['predicted_intent'])
    if not truth:raise ValueError('no unambiguous independent labels')
    ka=cohen_kappa_score([r['expected_intent']for r in a.values()],[b[q]['expected_intent']for q in a])
    quality={key:{'rater_A_mean':float(np.mean([int(r[key])for r in ra.values()if r[key]!='NA']))if any(r[key]!='NA'for r in ra.values())else None,
                  'rater_B_mean':float(np.mean([int(r[key])for r in rb.values()if r[key]!='NA']))if any(r[key]!='NA'for r in rb.values())else None,
                  'rater_A_denominator':sum(r[key]!='NA'for r in ra.values()),
                  'rater_B_denominator':sum(r[key]!='NA'for r in rb.values()),
                  'rater_A_NA':sum(r[key]=='NA'for r in ra.values()),
                  'rater_B_NA':sum(r[key]=='NA'for r in rb.values()),
                  'paired_agreement':sum(ra[q][key]==rb[q][key]for q in ra)/len(ra)}for key in RATINGS}
    adequate=sum(ra[q]['answer_correctness']=='2'and rb[q]['answer_correctness']=='2'for q in ra)/len(ra)
    return {'schema':'m6-independent-human-evaluation-v1','status':'scored_on_supplied_human_annotations',
        'packet_sha256':saved,'rows':len(a),'unambiguous_denominator':len(truth),'ambiguous_excluded_explicitly':ambiguous,
        'intent_accuracy':float(accuracy_score(truth,pred)),'intent_classification_report':classification_report(truth,pred,labels=INTENTS,output_dict=True,zero_division=0),
        'intent_confusion':confusion_matrix(truth,pred,labels=INTENTS).tolist(),'intent_label_order':INTENTS,
        'human_human_kappa':float(ka)if np.isfinite(ka)else None,'disagreements':conflicts,'human_quality_scores':quality,
        'independent_answer_adequacy_rate_both_raters':adequate,
        'annotation_hashes':{str(p):file_sha(p)for p in [intent_a,intent_b,ratings_a,ratings_b]+([adjudication]if adjudication else[])},
        'identities_self_declared_not_authenticated':True,'not_natural_language_model_or_clinical_accuracy':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare');a.add_argument('--output',type=Path,required=True)
    b=sub.add_parser('score');b.add_argument('--packet',type=Path,required=True)
    for name in ['intent-a','intent-b','ratings-a','ratings-b']:b.add_argument('--'+name,type=Path,required=True)
    b.add_argument('--adjudication',type=Path);b.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('fresh output required')
    if args.mode=='prepare':result=prepare(args.output)
    else:
        result=score(args.packet,args.intent_a,args.intent_b,args.ratings_a,args.ratings_b,args.adjudication)
        args.output.mkdir(parents=True);dump(args.output/'report.json',result)
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
