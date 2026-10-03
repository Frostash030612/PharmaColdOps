"""No outer-label selection, no cross-role leakage, and honest SHAP/calibration."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from ml.contracts import FEATURES
from ml.formal import (Dataset, outer_splits, inner_splits, audit_partition, ProbabilityCalibrator,
                       evaluate_fold, metrics, reliability, summarize)
from ml.training import make_pipeline

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import evaluate_m4 as experiments


def risk(n=240):
    rng=np.random.RandomState(42)
    x=pd.DataFrame({key:rng.normal(size=n) for key in FEATURES['risk']})
    y=(x.transit_days.to_numpy()+rng.normal(size=n)>.6).astype(int)
    return Dataset('risk',x,y,[f'S{i}' for i in range(n)])


def cause():
    n=720
    month=np.repeat(np.arange(24253,24271),40)
    groups=np.array([f'G{i%30}' for i in range(n)])
    values={k:['yes']*n for k in FEATURES['cause']}
    values.update(equipment_age_years=np.arange(n)%10,power_outage_hours_last_month=np.arange(n)%6,
                  year=(month-1)//12,month=(month-1)%12+1)
    x=pd.DataFrame(values)
    y=np.array([['a','b','c'][(i//30+i%30)%3] for i in range(n)])
    return Dataset('cause',x,y,[f'C{i}' for i in range(n)],groups,month)


@pytest.mark.parametrize('mode',['random','facility','time'])
def test_every_outer_and_inner_role_is_disjoint_reproducible(mode):
    data=cause()
    splits=outer_splits(data,mode,5)
    repeated=outer_splits(data,mode,5)
    tested=[]
    for n,((outer,test),(again,again_test)) in enumerate(zip(splits,repeated)):
        np.testing.assert_array_equal(outer,again);np.testing.assert_array_equal(test,again_test)
        parts=(*inner_splits(data,outer,mode,43+n),test)
        audit=audit_partition(data,parts,mode)
        assert audit['status']=='passed' and audit['row_overlap']==0
        assert set(np.concatenate(parts[:3]))==set(outer)
        if mode=='facility':assert audit['group_overlap']==0
        if mode=='time':assert audit['chronological_roles']
        tested.extend(test)
    assert len(tested)==len(set(tested))
    if mode!='time':assert set(tested)==set(range(len(data.y)))
    else:assert len(tested)<len(data.y)


def test_no_fabricated_timestamp_or_group_validation():
    with pytest.raises(ValueError,match='timestamps absent'):outer_splits(risk(),'time')
    with pytest.raises(ValueError,match='facility groups'):outer_splits(risk(),'facility')


@pytest.mark.parametrize('fault',['overlap','missing_class','future','group'])
def test_invalid_or_leaking_partition_fails_closed(fault):
    data=cause();outer,test=outer_splits(data,'time')[0]
    fit,cal,selection=inner_splits(data,outer,'time',42)
    mode='time'
    if fault=='overlap':cal=np.concatenate([cal,fit[:1]])
    if fault=='missing_class':fit=fit[data.y[fit]=='a']
    if fault=='future':fit,selection=selection,fit
    if fault=='group':mode='facility'
    with pytest.raises(ValueError):audit_partition(data,(fit,cal,selection,test),mode)


def test_outer_test_labels_cannot_affect_model_threshold_or_calibration():
    data=risk();outer,test=outer_splits(data,'random')[0]
    parts=(*inner_splits(data,outer,'random',43),test)
    changed=data.y.copy();changed[test]=np.random.RandomState(2).permutation(changed[test])
    shuffled=Dataset(data.task,data.x,changed,data.ids)
    candidates=[('lr',LogisticRegression(max_iter=500,random_state=42))]
    with threadpool_limits(limits=1):
        first,model,_=evaluate_fold(data,parts,candidates,'random')
        second,model2,_=evaluate_fold(shuffled,parts,candidates,'random')
    for field in ['algorithm','calibration','threshold','raw_threshold','candidates','calibration_candidates']:
        assert first[field]==second[field]
    np.testing.assert_allclose(model.predict_proba(data.x.iloc[test]),model2.predict_proba(data.x.iloc[test]))
    assert first['calibrated_metrics']!=second['calibrated_metrics']


def test_preprocessing_medians_fit_only_the_fit_role():
    data=risk();data.x.loc[0,'rh_max']=np.nan
    outer,test=outer_splits(data,'random')[0]
    parts=(*inner_splits(data,outer,'random',43),test)
    with threadpool_limits(limits=1):
        _,model,_=evaluate_fold(data,parts,[('lr',LogisticRegression(max_iter=500))],'random')
    imputer=model.model.named_steps['prepare'].named_transformers_['numeric'].named_steps['fill']
    np.testing.assert_allclose(imputer.statistics_,data.x.iloc[parts[0]].median().to_numpy())
    assert not np.allclose(imputer.statistics_,data.x.median().to_numpy())


@pytest.mark.parametrize('method',['none','sigmoid','isotonic','temperature'])
def test_calibrators_return_finite_normalized_probabilities(method):
    p=np.linspace(.01,.99,200);matrix=np.column_stack([1-p,p]);y=(np.arange(200)%5==0).astype(int)
    cal=ProbabilityCalibrator(method).fit(matrix,y)
    result=cal.transform(np.array([[1.,0.],[.1,.9],[0.,1.]]))
    assert np.isfinite(result).all() and (result>=0).all() and (result<=1).all()
    np.testing.assert_allclose(result.sum(axis=1),1)


def test_temperature_preserves_class_rank_not_fake_accuracy_improvement():
    p=np.array([[.7,.2,.1],[.1,.8,.1],[.2,.1,.7],[.6,.3,.1],[.1,.6,.3],[.1,.2,.7]])
    y=np.array([2,0,1,0,1,2])
    cal=ProbabilityCalibrator('temperature').fit(p,y)
    np.testing.assert_array_equal(p.argmax(axis=1),cal.transform(p).argmax(axis=1))


def test_calibration_metrics_and_reliability_use_correct_axes():
    p=np.array([[.9,.1],[.2,.8],[.6,.4],[.3,.7]])
    y=np.array([0,1,1,0])
    result=metrics('risk',y,p)
    assert result['brier']==pytest.approx(np.mean((p[:,1]-y)**2))
    curve=reliability(y,p[:,1]);assert sum(b['count']for b in curve['bins'])==4
    with pytest.raises(ValueError,match='probability'):metrics('risk',y,p*2)


def test_forbidden_target_ids_and_quantities_never_enter_model():
    for task,key in [('risk','silent_failure'),('risk','product_volume_l'),('cause','facility_id'),('cause','excursion_cause')]:
        with pytest.raises(ValueError):make_pipeline(task,LogisticRegression(),[key])
    manifest=experiments.feature_manifest()
    assert 'feature_x1' in manifest['forbidden_risk'] and manifest['facility_id_grouping_only_not_a_model_feature']


def test_summaries_are_fold_sd_not_claimed_confidence_intervals():
    folds=[{section:{'f1':value} for section in ['raw_metrics','calibrated_metrics','baseline_metrics']}for value in [.2,.4,.6]]
    summary=summarize(folds)
    assert summary['raw_metrics']['f1']['mean']==pytest.approx(.4)
    assert summary['raw_metrics']['f1']['std']==pytest.approx(.2)


def test_shap_real_explainer_axes_background_train_only_and_additivity(tmp_path):
    data=risk();data.x['temp_min_c']=-2;data.x['temp_mean_c']=0;data.x['temp_max_c']=2
    data.x['rh_mean']=.3;data.x['rh_max']=.4;data.x['rh_std']=.05
    for key in ['transit_days','temp_std_c','sensor_gap_hours','vibration_index']:data.x[key]=abs(data.x[key])
    data.x['door_opens']=2;data.x['leg_count']=1;data.x['temp_recovery_rate']=.5
    fit,test=np.arange(160),np.arange(160,240)
    model=make_pipeline('risk',LogisticRegression(max_iter=500))
    with threadpool_limits(limits=1):
        model.fit(data.x.iloc[fit],data.y[fit])
        result=experiments.shap_explanation(model,data,fit,test,tmp_path/'shap',{'scope':'unit-test','model_sha256':'unit-test'},rows=2,background=3,nsamples=32)
    assert result['method'].startswith('KernelSHAP') and result['local_additivity_max_residual']<1e-6
    assert set(result['background_sample_ids'])<=set(np.asarray(data.ids)[fit])
    assert set(result['held_out_sample_ids'])<=set(np.asarray(data.ids)[test])
    assert (tmp_path/'shap'/'values.npz').exists()


def test_fresh_output_cannot_overwrite_existing_evidence(tmp_path,monkeypatch):
    folder=tmp_path/'old';folder.mkdir();marker=folder/'report.json';marker.write_text('{"kept":true}')
    monkeypatch.setattr(sys,'argv',['evaluate_m4.py','--output',str(folder)])
    with pytest.raises(SystemExit):experiments.main()
    assert json.loads(marker.read_text())=={'kept':True}
