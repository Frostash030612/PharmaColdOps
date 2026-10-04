import hashlib
import json
from pathlib import Path
import sys

import pytest
from api import deployment
from ml import event_v2_runtime
from ml.event_gate import fingerprint, policy
from ml.event_temporal import VERSION, TEMPORAL_FEATURES
from ml.event_simulation import FEATURES as OBS_FEATURES
from ml.event_baselines import TARGETS
from ml.contracts import FEATURES

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from prepare_v2_shadow_deployment import prepare
import check_deployed_v2_shadow as live


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def sources(tmp_path):
    shadow,models=tmp_path/'shadow',tmp_path/'models';shadow.mkdir();models.mkdir()
    (shadow/'model.joblib').write_bytes(b'trusted local fixture, not unpickled by staging')
    (shadow/'demo_samples.json').write_text('[]')
    value=policy({'products':['vaccine_2_8'],'ranges':{k:[-100,100] for k in OBS_FEATURES if k!='product_id'}},[.5]*11)
    meta={'schema':event_v2_runtime.BUNDLE_SCHEMA,'feature_schema':VERSION,'features':list(TEMPORAL_FEATURES),'targets':list(TARGETS),
          'shadow_only':True,'review_required':True,'automatic_actions_allowed':False,'policy':value,'policy_sha256':fingerprint(value),
          'model_sha256':sha(shadow/'model.joblib'),'demo_samples_sha256':sha(shadow/'demo_samples.json'),'model_id':'fixture'}
    (shadow/'metadata.json').write_text(json.dumps(meta))
    for task in ['risk','cause']:
        folder=models/task;folder.mkdir();(folder/'model.joblib').write_bytes(('trusted '+task).encode())
        (folder/'metadata.json').write_text(json.dumps({'schema_version':1,'task':task,'features':FEATURES[task],'model_sha256':sha(folder/'model.joblib')}))
    return shadow,models


def test_stage_allowlist_exact_hashes_and_private_env_without_credentials(tmp_path,sources):
    shadow,models=sources
    (shadow/'labels.private.jsonl').write_text('never copy')
    out=tmp_path/'stage'
    report=prepare(out,shadow,models,'pharmacoldops-demo:shadow-test')
    assert report['status']=='staged_not_deployed' and len(report['files'])==7
    assert not (out/'shadow/labels.private.jsonl').exists()
    assert (out/'shadow.env').stat().st_mode & 0o777 == 0o600
    text=(out/'shadow.env').read_text()
    assert 'NEO4J_PASSWORD' not in text and 'DATABASE_URL' not in text and 'V2_SHADOW_IMAGE=' in text
    for name,h in report['files'].items():
        assert sha(out/name)==h and (out/name).stat().st_mode & 0o777 == 0o644
    with pytest.raises(ValueError): prepare(out,shadow,models,'pharmacoldops-demo:shadow-test')


@pytest.mark.parametrize('bad',['model','sample','policy','old_model','symlink','image'])
def test_invalid_source_refused_without_staging_or_service_mutation(tmp_path,sources,bad):
    shadow,models=sources;image='pharmacoldops-demo:shadow-test'
    if bad=='model': (shadow/'model.joblib').write_bytes(b'bad')
    elif bad=='sample': (shadow/'demo_samples.json').write_text('[1]')
    elif bad=='old_model': (models/'risk/model.joblib').write_bytes(b'bad')
    elif bad=='image': image='bad tag with spaces'
    elif bad=='symlink':
        (shadow/'model.joblib').unlink();(shadow/'model.joblib').symlink_to(models/'risk/model.joblib')
    else:
        path=shadow/'metadata.json';m=json.loads(path.read_text());m['policy']['review_required']=False;m['policy_sha256']=fingerprint(m['policy']);path.write_text(json.dumps(m))
    with pytest.raises(ValueError): prepare(tmp_path/'out',shadow,models,image)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('shadow_status,expected',[('shadow_ready','ready'),('disabled','not_ready'),('unavailable','not_ready')])
def test_enabled_shadow_is_a_readiness_dependency(monkeypatch,shadow_status,expected):
    monkeypatch.setenv('EVENT_V2_SHADOW_ENABLED','1');monkeypatch.setenv('DEPLOYMENT_REQUIRE_MODELS','0');monkeypatch.setenv('DEPLOYMENT_REQUIRE_GRAPH','0')
    monkeypatch.setattr(deployment,'storage_ready',lambda _:True)
    monkeypatch.setattr(event_v2_runtime,'info',lambda:{'status':shadow_status})
    result=deployment.ready_state()
    assert result['status']==expected
    assert result['checks']['event_v2_shadow']==('ready' if expected=='ready' else 'unavailable')


def test_disabled_shadow_does_not_change_legacy_ready_contract(monkeypatch):
    monkeypatch.delenv('EVENT_V2_SHADOW_ENABLED',raising=False);monkeypatch.setenv('DEPLOYMENT_REQUIRE_MODELS','0');monkeypatch.setenv('DEPLOYMENT_REQUIRE_GRAPH','0')
    monkeypatch.setattr(deployment,'storage_ready',lambda _:True)
    monkeypatch.setattr(event_v2_runtime,'info',lambda:pytest.fail('disabled shadow not inspected'))
    assert deployment.ready_state()['checks']=={'storage':'ready'}


def test_overlay_explicit_paths_readonly_no_host_path_creation():
    import yaml
    overlay=yaml.safe_load((Path(__file__).resolve().parents[1]/'deploy/compose.v2-shadow.yml').read_text())
    api=overlay['services']['api']
    assert api['environment']['EVENT_V2_SHADOW_ENABLED']=='1'
    assert {v['target'] for v in api['volumes']}=={'/app/models','/app/event-v2-shadow'}
    assert all(v['read_only'] is True and v['bind']['create_host_path'] is False for v in api['volumes'])
    assert 'neo4j' not in overlay['services'] and 'ports' not in api and 'command' not in api


@pytest.mark.parametrize('base',['https://127.0.0.1:8080','http://example.com','http://user:secret@localhost:8080','http://localhost/path','http://localhost?x=1','http://localhost#x'])
def test_live_acceptance_refuses_nonloopback_or_credential_urls(base):
    with pytest.raises(ValueError):live.validate_base(base)


@pytest.mark.parametrize('asset',['./assets/index.js','/assets/index.js'])
def test_live_checker_accepts_relative_vite_assets_but_writes_no_cases(monkeypatch,asset):
    state={'models':{t:{'status':'ready','model_id':t,'model_sha256':t+'sha'} for t in ['risk','cause']},'case_response':{'runs':[]},'dispatch_response':{'runs':[]}}
    calls=[]
    monkeypatch.setattr(live,'inventory',lambda _:state)
    def fetch(base,path,body=None):
        calls.append((path,body))
        if path=='/api/ready':return {'status':'ready','checks':{'event_v2_shadow':'ready'}}
        if path=='/api/ml/event/v2/info':return {'status':'shadow_ready','feature_count':111,'model_sha256':'m','policy_sha256':'p','review_required':True,'automatic_actions_allowed':False}
        if path=='/':return f'<script src="{asset}"></script>'
        if path=='/assets/index.js':return 'same-origin event_v2_context'
        if path=='/api/ml/event/v2/samples':return {'samples':[{'sample_id':'s','role':'test_nominal','observation':{}}]}
        if path=='/api/ml/event/v2/assess':return {'status':'abstained','model_sha256':'m','policy_sha256':'p','review_required':True,'automatic_actions_allowed':False,'candidates':[],'scores':{},'observation_sha256':'o'}
        pytest.fail('unexpected endpoint')
    monkeypatch.setattr(live,'request',fetch)
    report=live.check('http://127.0.0.1:8080',{'inventory':state})
    assert report['status']=='passed' and report['samples_checked']==1
    assert all(path=='/api/ml/event/v2/assess' for path,body in calls if body is not None)


def test_live_checker_refuses_existing_state_changes(monkeypatch):
    monkeypatch.setattr(live,'inventory',lambda _:{'different':'records'})
    with pytest.raises(ValueError,match='preserved baseline'):live.check('http://127.0.0.1:8080',{'inventory':{}})
