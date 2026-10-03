"""Independent v2 contract, explicit opt-in and non-bypassable review."""
import copy
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from threadpoolctl import threadpool_limits

from api import service
from api.main import app
from ml import event_v2_runtime as runtime
from ml.event_gate import fingerprint, policy
from ml.event_temporal import VERSION, TEMPORAL_FEATURES, extract_temporal, make_temporal_pipeline
from ml.event_baselines import TARGETS
from ml.event_simulation import FEATURES, CHANNELS, VERSION as OBS_VERSION, temperature_series
from optimisation.case_repository import registered_records

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import package_event_v2_shadow as packaging
client = TestClient(app)


def observation():
    rows=[]
    for start in range(0,120,5):
        row={key:0. for key in CHANNELS}
        row.update(start_min=start,end_min=start+5,product_temp_c=5.,air_temp_c=5.,ambient_temp_c=25.,mains_available=1.,
                   fuel_fraction=.8,airflow_fraction=.9,setpoint_c=5.,humidity_pct=50.)
        rows.append(row)
    return {"schema":OBS_VERSION,"source":"simulated","event_id":"EV-v2-shadow-test","product_id":"vaccine_2_8",
            "planned_duration_min":180,"observation_end_min":120,"sample_cadence_min":5,"records":rows}


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.delenv("EVENT_V2_SHADOW_ENABLED",raising=False);monkeypatch.delenv("EVENT_V2_SHADOW_DIR",raising=False)
    runtime._cache.clear()
    monkeypatch.setattr(service,"DISPATCH_DATABASE_URL",str(tmp_path/"cases.sqlite3"))
    monkeypatch.setattr(service,"RUNS_FILE",tmp_path/"cases.jsonl")
    monkeypatch.setattr(service,"write_case",lambda r:True)
    monkeypatch.setattr(service,"evidence_snapshot",lambda n:{"status":"not_verified"})


@pytest.fixture
def bundle(tmp_path):
    root=tmp_path/"bundle";root.mkdir()
    x=pd.DataFrame([extract_temporal(observation(),service.ENGINE.specs)]*40,columns=TEMPORAL_FEATURES)
    y=np.stack([np.arange(40)%(i+2)==0 for i in range(11)],axis=1).astype(int)
    model=make_temporal_pipeline()
    with threadpool_limits(limits=1): model.fit(x,y)
    joblib.dump(model,root/"model.joblib")
    samples=[{"sample_id":"public-demo","role":"test_nominal","observation":observation()}]
    (root/"demo_samples.json").write_text(json.dumps(samples))
    envelope={"products":["vaccine_2_8"],"ranges":{k:[-10000.,10000.] for k in FEATURES if k!="product_id"}}
    value=policy(envelope,[.5]*11)
    import sklearn
    meta={"schema":runtime.BUNDLE_SCHEMA,"feature_schema":VERSION,"features":list(TEMPORAL_FEATURES),"targets":list(TARGETS),
          "model_id":"v2-shadow-test-model","model_sha256":runtime.digest(root/"model.joblib"),"sklearn_version":sklearn.__version__,
          "policy":value,"policy_sha256":fingerprint(value),"demo_samples_sha256":runtime.digest(root/"demo_samples.json"),
          "study_selection_sha256":"study-test","shadow_only":True,"review_required":True,"automatic_actions_allowed":False}
    (root/"metadata.json").write_text(json.dumps(meta))
    return root


def request():
    obs=observation()
    return {"product_id":obs["product_id"],"packaging":"intact","registration_id":"v2-case",
            "event_v2_context":{"observation":obs},"temperature_context":{"series":temperature_series(obs,service.ENGINE.specs).model_dump(),"window_id":None}}


def enable(monkeypatch,bundle):
    monkeypatch.setenv("EVENT_V2_SHADOW_ENABLED","1");monkeypatch.setenv("EVENT_V2_SHADOW_DIR",str(bundle))


@pytest.mark.parametrize("flag",[None,"0","true","yes"])
def test_explicit_switch_required_even_with_valid_directory(bundle,monkeypatch,flag):
    monkeypatch.setenv("EVENT_V2_SHADOW_DIR",str(bundle))
    if flag: monkeypatch.setenv("EVENT_V2_SHADOW_ENABLED",flag)
    monkeypatch.setattr(joblib,"load",lambda *a:pytest.fail("disabled shadow must not unpickle"))
    assert client.get('/api/ml/event/v2/info').json()['status']=='disabled'
    assert client.get('/api/ml/event/v2/samples').status_code==503
    result=client.post('/api/ml/event/v2/assess',json={'observation':observation()}).json()
    assert result['status']=='disabled' and result['review_required'] and not result['automatic_actions_allowed']
    assert not Path(service.DISPATCH_DATABASE_URL).exists() and not service.RUNS_FILE.exists()


def test_enabled_real_model_is_readonly_and_returns_same_m2_evidence(bundle,monkeypatch):
    enable(monkeypatch,bundle)
    assert client.get('/api/ml/event/v2/info').json()['feature_count']==111
    samples=client.get('/api/ml/event/v2/samples').json()
    assert set(samples['samples'][0])=={'sample_id','role','observation'}
    response=client.post('/api/ml/event/v2/assess',json={'observation':observation()})
    assert response.status_code==200
    result=response.json()
    assert result['status'] in {'candidate_only','abstained'} and result['model_id']=='v2-shadow-test-model'
    assert result['feature_schema']==VERSION and result['temperature_series']==temperature_series(observation(),service.ENGINE.specs).model_dump()
    assert not Path(service.DISPATCH_DATABASE_URL).exists()


@pytest.mark.parametrize('extra',[{'scores':{}},{'model_path':'/tmp/model'},{'review_required':False},{'features':{}}])
def test_client_cannot_supply_model_scores_paths_or_features(extra):
    assert client.post('/api/ml/event/v2/assess',json={'observation':observation(),**extra}).status_code==422


@pytest.mark.parametrize('bad',['nan','label','bool_time'])
def test_bad_observations_return_safe_422_without_echo_or_500(bad):
    obs=observation()
    if bad=='nan': obs['records'][0]['fuel_fraction']=float('inf')
    elif bad=='label': obs['hidden_plan']={'faults':[]}
    else: obs['planned_duration_min']=True
    response=client.post('/api/ml/event/v2/assess',content=json.dumps({'observation':obs}),headers={'Content-Type':'application/json'})
    assert response.status_code==422 and 'input' not in response.json()['detail'][0]


@pytest.mark.parametrize('part',['model','sample','policy','version'])
def test_invalid_artifacts_fail_closed_before_unpickle(bundle,monkeypatch,part):
    enable(monkeypatch,bundle)
    meta=json.loads((bundle/'metadata.json').read_text())
    if part=='model': (bundle/'model.joblib').write_bytes(b'broken')
    elif part=='sample': (bundle/'demo_samples.json').write_text('[]')
    elif part=='version': meta['sklearn_version']='wrong'
    else:
        meta['policy']['review_required']=False;meta['policy_sha256']=fingerprint(meta['policy'])
    (bundle/'metadata.json').write_text(json.dumps(meta))
    monkeypatch.setattr(joblib,'load',lambda *a:pytest.fail('invalid artifact must not unpickle'))
    result=client.post('/api/ml/event/v2/assess',json={'observation':observation()}).json()
    assert result['status']=='unavailable' and result['review_required']


def test_case_must_bind_complete_evidence_and_choose_one_version():
    for change in ['missing','temperature','product','both']:
        body=request()
        if change=='missing':body.pop('temperature_context')
        elif change=='temperature':body['temperature_context']['series']['intervals'][0]['temp_c']=7
        elif change=='product':body['event_v2_context']['observation']['product_id']='insulin_2_8'
        else:body['event_context']=copy.deepcopy(body['event_v2_context'])
        assert client.post('/api/case_close',json=body).status_code==422
    assert registered_records(service.DISPATCH_DATABASE_URL)==[]


def test_disabled_case_still_requires_review_not_silent_v1_fallback():
    response=client.post('/api/case_close',json=request())
    assert response.status_code==200,response.text
    record=response.json()
    assert record['event_v2_assessment']['status']=='disabled' and 'event_assessment' not in record
    assert record['review_status']=='pending' and record['effective_disposition'] is None
    assert client.post('/api/dispatch/reshipments/preview',json={'run_id':record['run_id']}).status_code==422


def test_registration_freezes_v2_snapshot_retries_and_human_outcome(bundle,monkeypatch):
    enable(monkeypatch,bundle);body=request()
    record=client.post('/api/case_close',json=body).json()
    assert record['event_v2_assessment']['model_id']=='v2-shadow-test-model' and record['review_status']=='pending'
    original=copy.deepcopy(registered_records(service.DISPATCH_DATABASE_URL))
    monkeypatch.setattr(runtime,'evaluate',lambda *a:pytest.fail('retry must not re-evaluate'))
    assert client.post('/api/case_close',json=body).json()==record
    changed=copy.deepcopy(body);changed['event_v2_context']['observation']['records'][0]['humidity_pct']=60
    assert client.post('/api/case_close',json=changed).status_code==409
    assert client.post(f"/api/runs/{record['run_id']}/workflow",json={'status':'handled','expected_version':0,'remark':'bypass'}).status_code==409
    review=client.post(f"/api/runs/{record['run_id']}/review",json={'command_id':'v2-human','expected_version':record['workflow_version'],
        'reviewer':'Demo reviewer','reason':'Independent review of complete simulated evidence','disposition':'release'})
    assert review.status_code==200 and review.json()['effective_disposition']=='release'
    assert registered_records(service.DISPATCH_DATABASE_URL)==original
    assert service.find_run(record['run_id'])['event_v2_assessment']==record['event_v2_assessment']


def test_linked_delivery_stays_held_until_review(day_plan,bundle,monkeypatch):
    enable(monkeypatch,bundle)
    did=day_plan('PLAN-V2-SHADOW',hospitals=1)
    order=service.get_dispatch(did)['input']['orders'][0]
    body=request();obs=body['event_v2_context']['observation'];obs['product_id']=order['product_id']
    body.update(product_id=order['product_id'],dispatch_id=did,order_id=order['order_id'],destination_facility_id=order['destination_facility_id'])
    record=client.post('/api/case_close',json=body).json()
    service.depart_dispatch(did,'depart',speed=0)
    vehicle=next(k for k,v in service.get_dispatch(did)['vehicles'].items() if order['order_id'] in v['remaining_order_ids'])
    with pytest.raises(ValueError,match='held'):service.deliver_dispatch(did,vehicle,'blocked')
    response=client.post(f"/api/runs/{record['run_id']}/review",json={'command_id':'v2-release','expected_version':record['workflow_version'],
        'reviewer':'Demo reviewer','reason':'Explicit review before delivery','disposition':'release'})
    assert response.status_code==200
    service.deliver_dispatch(did,vehicle,'reviewed')
    assert service.find_run(record['run_id'])['execution_locked']


def test_packager_uses_public_first_samples_without_labels_or_scores(tmp_path,bundle):
    study=tmp_path/'study';(study/'data').mkdir(parents=True)
    meta=json.loads((bundle/'metadata.json').read_text())
    import shutil
    shutil.copyfile(bundle/'model.joblib',study/'mixed_temporal.joblib')
    manifest={'schema':VERSION,'status':'complete','roles':{}}
    for role in packaging.TEST:
        folder=study/'data'/role;folder.mkdir()
        file=folder/'observations.jsonl';file.write_text(json.dumps(observation())+'\n')
        manifest['roles'][role]={'file_sha256':{file.name:packaging.digest(file)}}
    (study/'data/manifest.json').write_text(json.dumps(manifest))
    (study/'protocol.json').write_text('{}')
    frozen={'schema':VERSION,'selected':'mixed_temporal','protocol_sha256':packaging.digest(study/'protocol.json'),
            'model_sha256':{'mixed_temporal':meta['model_sha256']},'policies':{'mixed_temporal':meta['policy']}}
    (study/'selection-frozen.json').write_text(json.dumps(frozen))
    (study/'report.json').write_text(json.dumps({'status':'complete','schema':VERSION,'selected':'mixed_temporal',
        'selection_sha256':packaging.digest(study/'selection-frozen.json'),'dataset_manifest_sha256':packaging.digest(study/'data/manifest.json'),
        'protocol':{'versions':{'sklearn':meta['sklearn_version']}}}))
    result=packaging.package(study,tmp_path/'packed')
    assert result['status']=='packaged_not_enabled' and result['samples']==5
    samples=json.loads((tmp_path/'packed/demo_samples.json').read_text())
    assert all(set(s)=={'sample_id','role','observation'} for s in samples)
    with pytest.raises(ValueError):packaging.package(study,tmp_path/'packed')
