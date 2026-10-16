"""Coordinator process gates and missing-input handling, not human gold."""
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import finalize_m6_review as workflow


def process_fixture(tmp_path):
    paths, annotations = {}, {}
    record = {'schema':'m6-human-review-process-v1', 'packet_sha256':'unit-packet', 'coordinator_id':'unit-coordinator',
              'answers_disclosed_at':'2026-10-17T12:00:00+08:00', 'reviewers':{}}
    for role in ('A','B'):
        actor = 'unit-'+role
        data = {'annotator_id':actor, 'human_confirmed':True, 'independent_intent_confirmed':True,
                'sources_consulted_confirmed':True, 'intent_sealed_at':'2026-10-17T11:00:00+08:00',
                'ratings_submitted_at':'2026-10-17T13:00:00+08:00'}
        for phase in ('intent','ratings'):
            key = phase+'_'+role.lower()
            paths[key] = tmp_path/(key+'.csv')
            paths[key].write_text('unit fixture only: '+key,encoding='utf-8')
            annotations[key] = {'unit-Q':{'annotator_id':actor}}
            data[phase+'_sha256'] = workflow.evaluator.file_sha(paths[key])
        record['reviewers'][role] = data
    return paths, annotations, record


def test_process_requires_explicit_human_and_seal_declarations(tmp_path):
    paths, annotations, record = process_fixture(tmp_path)
    workflow.validate_process(record, {'packet_sha256':'unit-packet'}, annotations, paths)
    for key in ['human_confirmed','independent_intent_confirmed','sources_consulted_confirmed']:
        bad = copy.deepcopy(record)
        bad['reviewers']['B'][key] = None
        with pytest.raises(ValueError,match='not been confirmed'):
            workflow.validate_process(bad, {'packet_sha256':'unit-packet'}, annotations, paths)


def test_process_rejects_late_intent_or_changed_sealed_file(tmp_path):
    paths, annotations, record = process_fixture(tmp_path)
    late = copy.deepcopy(record)
    late['reviewers']['B']['intent_sealed_at']='2026-10-17T12:01:00+08:00'
    with pytest.raises(ValueError,match='sealed before answers'):
        workflow.validate_process(late, {'packet_sha256':'unit-packet'}, annotations, paths)
    paths['intent_a'].write_text('unit fixture edited after sealing',encoding='utf-8')
    with pytest.raises(ValueError,match='hash differs'):
        workflow.validate_process(record, {'packet_sha256':'unit-packet'}, annotations, paths)


def test_process_rejects_naive_time_and_reused_reviewer(tmp_path):
    paths, annotations, record = process_fixture(tmp_path)
    naive = copy.deepcopy(record)
    naive['answers_disclosed_at']='2026-10-17T12:00:00'
    with pytest.raises(ValueError,match='timezone'):
        workflow.validate_process(naive, {'packet_sha256':'unit-packet'}, annotations, paths)
    record['reviewers']['B']['annotator_id']='unit-A'
    for phase in ('intent','ratings'):
        annotations[phase+'_b']['unit-Q']['annotator_id']='unit-A'
    with pytest.raises(ValueError,match='must differ'):
        workflow.validate_process(record, {'packet_sha256':'unit-packet'}, annotations, paths)


def test_missing_B_produces_pending_inventory_without_scores_or_doc_updates(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(workflow,'update_docs',lambda result:called.append(result))
    paths={'intent_a':ROOT/'data/qa/m6-completed-20261016-intent-A.csv',
           'ratings_a':ROOT/'data/qa/m6-completed-20261016-ratings-A.csv',
           'intent_b':None, 'ratings_b':None}
    output=tmp_path/'new'
    result=workflow.run(paths,workflow.PACKET,output,apply_docs=True)
    assert result['status']=='awaiting_inputs' and result['human_metrics'] is None
    assert result['missing']==['intent_b','ratings_b']
    assert not (output/'report.json').exists() and not called
    record=json.loads((output/'process-record-template.json').read_text(encoding='utf-8'))
    assert record['reviewers']['A']['human_confirmed'] is None
    assert not record['reviewers']['B']['annotator_id']
    with pytest.raises(FileExistsError):
        workflow.run(paths,workflow.PACKET,output)


def test_disagreement_list_contains_human_labels_but_no_private_predictions():
    a={'Q':{'expected_intent':'audit_chain','acceptable_intents':'','note':'unit A'}}
    b={'Q':{'expected_intent':'why_disposition','acceptable_intents':'','note':'unit B'}}
    result=workflow.disagreements(a,b,{'questions':[{'question_id':'Q','question':'unit question'}]})
    assert result[0]['label_A']=='audit_chain' and result[0]['label_B']=='why_disposition'
    assert 'predicted_intent' not in result[0]


def test_doc_blocks_are_explicit_and_missing_markers_fail_before_update():
    original='before\n<!-- UNIT_START -->\nold\n<!-- UNIT_END -->\nafter'
    replaced=workflow.replace_block(original,'UNIT','unit result')
    assert 'before' in replaced and 'after' in replaced and 'unit result' in replaced
    with pytest.raises(ValueError,match='markers'):
        workflow.replace_block('no markers','UNIT','unit result')


def test_all_doc_markers_are_checked_before_any_write(tmp_path, monkeypatch):
    first = tmp_path / 'first.md'
    first.write_text('before\n<!-- FIRST_START -->\nold\n<!-- FIRST_END -->', encoding='utf-8')
    second = tmp_path / 'second.md'
    second.write_text('unit document with missing markers', encoding='utf-8')
    before = first.read_bytes()
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    monkeypatch.setattr(workflow, 'MARKERS', {'first.md':['FIRST'], 'second.md':['SECOND']})
    monkeypatch.setattr(workflow, 'summary', lambda result:'unit fixture, not human evaluation')
    with pytest.raises(ValueError, match='markers'):
        workflow.update_docs({})
    assert first.read_bytes() == before


def test_explicit_unit_packet_cannot_become_a_formal_report(tmp_path):
    packet = {'schema':'m6-blind-packet-v1', 'unit_fixture_not_real_human_evaluation':True,
              'questions':[], 'responses':[]}
    packet['packet_sha256'] = workflow.evaluator.sha(packet)
    path = tmp_path / 'unit-packet.json'
    path.write_text(json.dumps(packet), encoding='utf-8')
    with pytest.raises(ValueError, match='unit fixtures'):
        workflow.read_packet(path)
