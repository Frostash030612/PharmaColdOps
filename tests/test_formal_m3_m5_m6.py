"""Formal evaluation must preserve truth, eligibility, timings and blind labels."""
import copy
from contextlib import nullcontext
import csv
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import evaluate_m3_formal as m3
import evaluate_m5_formal as m5
import evaluate_m6_independent as m6
import run_routing_baselines as legacy
from optimisation.greedy import solve_greedy
from optimisation.solomon_loader import load_dir


def test_real_m3_report_retains_all_four_labels_and_known_deviations():
    report,rows=m3.evaluate()
    assert report['rows']==57 and report['agree']==54
    assert report['engine_vs_gold_kappa']==pytest.approx(.9096671949286846)
    assert report['class_report']['macro avg']['f1-score']==pytest.approx((26/28+16/17+0+1)/4)
    assert report['class_report']['quarantine']['support']==3 and report['class_report']['quarantine']['recall']==0
    assert {r['scenario_id']for r in report['deviations']}=={'S034','S035','S052'}
    assert set(report['rule_coverage'])==set('123456') and all('automatic_disposition'in r for r in rows)


def test_m3_wrong_or_duplicate_labels_fail_closed(tmp_path):
    path=tmp_path/'bad.csv';path.write_text('scenario_id,gold_label\nS001,release\nS001,scrap\n')
    with pytest.raises(ValueError,match='duplicate'):m3.evaluate(gold=path)
    path.write_text('scenario_id,gold_label\nS001,release\n')
    with pytest.raises(ValueError,match='identities differ'):m3.evaluate(gold=path)


def test_m3_outputs_fresh_and_do_not_edit_evidence(tmp_path):
    report,rows=m3.evaluate();before=[m3.sha(p)for p in [m3.INPUT,m3.GOLD,m3.CONFIG]]
    m3.write_report(tmp_path/'new',report,rows)
    assert (tmp_path/'new'/'confusion.png').exists()
    with pytest.raises(FileExistsError):m3.write_report(tmp_path/'new',report,rows)
    assert before==[m3.sha(p)for p in [m3.INPUT,m3.GOLD,m3.CONFIG]]


def test_empty_infeasible_route_cannot_win_or_claim_bks_gap():
    instance=load_dir()['C101'];good=solve_greedy(instance)
    complete=m5.row_for(instance,good,.3,None,None)
    empty=replace(good,routes=(),metrics=replace(good.metrics,total_distance=0,vehicles_used=0,served_customers=0,unserved_customer_ids=tuple(n.node_id for n in instance.customers)))
    partial=m5.row_for(instance,empty,60,60,42)
    assert not partial['complete_feasible'] and partial['gap_distance_pct']is None
    assert m5.best_rows([partial,complete])['C101']==complete
    assert m5.best_rows([partial])['C101']is None
    fake={'instance':'C101','vehicles':0,'distance':0,'unserved':100,'violations':100,'algorithm':'empty','budget':60}
    valid={'instance':'C101','vehicles':10,'distance':850,'unserved':0,'violations':0,'algorithm':'valid','budget':60}
    assert 'valid' in '\n'.join(legacy._best_summary([fake,valid]))


def test_different_fleet_no_distance_gap_runtime_never_replaced():
    instance=load_dir()['C101'];result=solve_greedy(instance)
    changed=replace(result,metrics=replace(result.metrics,vehicles_used=11))
    row=m5.row_for(instance,changed,4545,60,42)
    assert row['gap_distance_pct']is None and row['measured_seconds']==4545 and row['runtime_exceeds_budget']
    assert legacy._runtime_cell({'budget':60,'seconds':4545})=='4545.0 ⚠'


def test_route_metric_drift_or_cross_vehicle_duplicates_refused():
    instance=load_dir()['C101'];result=solve_greedy(instance)
    assert m5.validate_result(instance,result).metrics==result.metrics
    with pytest.raises(ValueError,match='metric drift'):m5.validate_result(instance,replace(result,metrics=replace(result.metrics,total_distance=1)))
    with pytest.raises(ValueError,match='repeated'):m5.validate_result(instance,replace(result,routes=(*result.routes,result.routes[0])))


def packet(tmp_path):
    questions=[{'question_id':f'Q{i}','question':q,'lang':'en'}for i,q in enumerate(['why','audit','weather'])]
    responses=[{**q,'predicted_intent':p,'response':{'answer':'example','status':'ok','evidence':[]},'response_sha256':f'R{i}'}for i,(q,p)in enumerate(zip(questions,['why_disposition','audit_chain','unsupported']))]
    manifest={'schema':'m6-blind-packet-v1','unit_fixture_not_real_human_evaluation':True,'questions':questions,'responses':responses}
    manifest['packet_sha256']=m6.sha(manifest)
    path=tmp_path/'packet.json';m6.dump(path,manifest)
    return path,manifest


def annotate(tmp_path,manifest,actor,kind,labels=None):
    rows=[]
    for i,q in enumerate(manifest['questions']):
        r={'question_id':q['question_id'],'packet_sha256':manifest['packet_sha256'],'annotator_id':actor}
        if kind=='intent':r.update(expected_intent=(labels or ['why_disposition','audit_chain','unsupported'])[i],acceptable_intents='',note='unit fixture only')
        else:r.update(response_sha256=f'R{i}',**{k:'2'if k not in ['refusal_appropriate','unsupported_claims']else '0'for k in m6.RATINGS},checked_source_urls='unit source, not real independent evidence',relevant_evidence_ids='',note='unit fixture only')
        rows.append(r)
    p=tmp_path/f'{kind}-{actor}.csv';m6.csv_write(p,list(rows[0]),rows);return p


def test_m6_actual_router_is_shared_and_legacy_words_not_assumed_human_truth():
    rows=[{'question_id':'x','question':'why this case','lang':'en'},{'question_id':'y','question':'mkt','lang':'en'}]
    pred=m6.predictions(rows)
    assert pred['x']['predicted_intent']=='why_disposition' and pred['y']['predicted_intent']=='unsupported'
    assert len(m6.questions())==53


def test_m6_blank_labels_are_not_zero_or_perfect_score(tmp_path):
    path,manifest=packet(tmp_path)
    a=annotate(tmp_path,manifest,'A','intent',labels=['','',''])
    b=annotate(tmp_path,manifest,'B','intent');ra=annotate(tmp_path,manifest,'A','ratings');rb=annotate(tmp_path,manifest,'B','ratings')
    with pytest.raises(ValueError,match='unlabelled'):m6.score(path,a,b,ra,rb)


def test_m6_complete_distinct_labels_and_real_packet_required(tmp_path):
    path,manifest=packet(tmp_path)
    a=annotate(tmp_path,manifest,'A','intent');b=annotate(tmp_path,manifest,'B','intent');ra=annotate(tmp_path,manifest,'A','ratings');rb=annotate(tmp_path,manifest,'B','ratings')
    result=m6.score(path,a,b,ra,rb)
    assert result['intent_accuracy']==1 and result['independent_answer_adequacy_rate_both_raters']==1
    assert result['human_quality_scores']['answer_correctness']['rater_A_denominator']==3
    assert result['identities_self_declared_not_authenticated']
    with pytest.raises(ValueError,match='must differ'):m6.score(path,a,a,ra,ra)
    changed=copy.deepcopy(manifest);changed['responses'][0]['response']['answer']='tampered';m6.dump(path,changed)
    with pytest.raises(ValueError,match='packet contents changed'):m6.score(path,a,b,ra,rb)


def test_m6_disagreements_require_provenanced_adjudication(tmp_path):
    path,manifest=packet(tmp_path)
    a=annotate(tmp_path,manifest,'A','intent');b=annotate(tmp_path,manifest,'B','intent',labels=['cause_context','audit_chain','unsupported']);ra=annotate(tmp_path,manifest,'A','ratings');rb=annotate(tmp_path,manifest,'B','ratings')
    with pytest.raises(ValueError,match='require human adjudication'):m6.score(path,a,b,ra,rb)
    p=tmp_path/'adjudicate.csv';row={'question_id':'Q0','packet_sha256':manifest['packet_sha256'],'adjudicator_id':'C','expected_intent':'why_disposition','note':'unit test manual adjudication fixture'}
    m6.csv_write(p,list(row),[row]);assert m6.score(path,a,b,ra,rb,p)['intent_accuracy']==1


def test_m6_wrong_packet_missing_rows_or_sources_refused(tmp_path):
    _,manifest=packet(tmp_path);p=annotate(tmp_path,manifest,'A','ratings')
    with p.open()as f:rows=list(csv.DictReader(f))
    rows[0]['checked_source_urls']='';m6.csv_write(p,list(rows[0]),rows)
    with pytest.raises(ValueError,match='provenance missing'):m6.read_annotations(p,manifest,'ratings')
    rows[0]['checked_source_urls']='test';rows=rows[:-1];m6.csv_write(p,list(rows[0]),rows)
    with pytest.raises(ValueError,match='all packet rows'):m6.read_annotations(p,manifest,'ratings')


def test_m6_unknown_packet_schema_or_mismatched_responses_rejected(tmp_path):
    path,manifest=packet(tmp_path)
    for mutation in ['schema','rows']:
        bad=copy.deepcopy(manifest);bad.pop('packet_sha256')
        if mutation=='schema':bad['schema']='unknown'
        else:bad['responses']=bad['responses'][:-1]
        bad['packet_sha256']=m6.sha(bad);m6.dump(path,bad)
        with pytest.raises(ValueError,match='packet schema|identities differ'):m6.score(path,None,None,None,None)


def test_m6_failed_contract_retains_report_cleans_up_and_does_not_release_packet(tmp_path,monkeypatch):
    monkeypatch.setattr(m6,'predictions',lambda _: {})
    monkeypatch.setattr(m6.contract,'_store',lambda *_:nullcontext())
    monkeypatch.setattr(m6.contract,'_graph',lambda *_:nullcontext(None))
    monkeypatch.setattr(m6.contract,'_evaluate',lambda *_:{'checks_failed':1,'checks_run':1})
    monkeypatch.setattr(m6,'read_case_originals',lambda *_args,**_kwargs:([],{}))
    clean=[]
    monkeypatch.setattr(m6.contract,'_cleanup',lambda *_:clean.append(True))
    output=tmp_path/'failed'
    with pytest.raises(RuntimeError,match='contract checks failed'):m6.prepare(output)
    assert clean==[True]
    assert json.loads((output/'derived-contract-report.json').read_text())['checks_failed']==1
    assert not (output/'pending-report.json').exists()
