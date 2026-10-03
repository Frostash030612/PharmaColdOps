import copy
from dataclasses import replace
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from ml.event_simulation import Asset, CHANNELS, FEATURES, Fault, Plan, VERSION as OBS_VERSION, extract_features, hidden_labels, simulate, twin
from ml.event_temporal import TEMPORAL_FEATURES, extract_temporal, make_temporal_pipeline, temporal_probabilities, validate_temporal
from ml.event_baselines import TARGETS, make_pipeline
from rule_engine.engine import RuleEngine

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import event_v2_data as data
import evaluate_event_v2 as evaluation
SPECS = RuleEngine().specs


def observation():
    rows = []
    for i,temp in enumerate([5.,7.,9.,11.]):
        row = {key:0. for key in CHANNELS}
        row.update(start_min=i*5.,end_min=(i+1)*5.,product_temp_c=temp,air_temp_c=temp+1,ambient_temp_c=25.,
                   mains_available=float(i<2),backup_command=float(i>=2),fuel_fraction=[.8,.7,.05,.02][i],
                   airflow_fraction=.9,setpoint_c=5.,compressor_current_fraction=.1,cooling_duty_fraction=.8)
        rows.append(row)
    return {"schema":OBS_VERSION,"source":"simulated","event_id":"EV-temporal-test","product_id":"vaccine_2_8",
            "planned_duration_min":180,"observation_end_min":20.,"sample_cadence_min":5,"records":rows}


def test_bins_and_joint_fuel_statistics_are_only_measured_prefix():
    obs = observation(); f = extract_temporal(obs,SPECS)
    assert len(f)==111 and tuple(f)==TEMPORAL_FEATURES
    assert {k:f[k] for k in FEATURES}==extract_features(obs,SPECS)
    assert [f[f"prefix_bin{i}_temperature_offset_mean"] for i in range(4)]==[0,2,4,6]
    assert f["mains_unavailable_fuel_mean"]==.035 and f["mains_unavailable_fuel_q10"]==.02
    assert f["fuel_on_minus_off_mean"]==.715 and f["fuel_after_minus_before_first_mains_loss"]==-.715
    assert f["mains_unavailable_fuel_low_known_min"]==10 and f["mains_unavailable_fuel_available_known_min"]==0
    assert f["mains_unavailable_backup_command_fraction"]==1 and f["commanded_not_running_known_min"]==10
    assert f["first_last_temperature_delta"]==6 and f["air_product_gradient_q90"]==1


def test_weighted_bins_clip_intervals_not_round_or_use_planned_future():
    obs = observation(); obs["observation_end_min"]=19.; obs["records"][-1]["end_min"]=19.
    f = extract_temporal(obs,SPECS)
    assert f["prefix_bin0_temperature_offset_mean"]==0
    assert f["prefix_bin1_temperature_offset_mean"]==pytest.approx(1.894737)
    assert f["prefix_bin3_temperature_coverage"]==1


def test_missing_conditionals_stay_null_known_zero_only_with_valid_evidence():
    obs = observation()
    for row in obs["records"]:
        for key in CHANNELS: row[key]=None
    f = extract_temporal(obs,SPECS)
    assert f["mains_unavailable_fuel_mean"] is None and f["airflow_low_known_min"] is None
    assert f["prefix_bin0_temperature_offset_mean"] is None and f["prefix_bin0_temperature_coverage"]==0
    assert f["temperature_gap_count"]==1 and f["first_last_temperature_delta"] is None


@pytest.mark.parametrize("key",["hidden_plan","label_kind","injected_causes","role","asset_id"])
def test_hidden_fields_are_refused_before_feature_extraction(key):
    obs = observation(); obs[key]="hidden"
    with pytest.raises(ValueError): extract_temporal(obs,SPECS)


def plan(code="generator_fuel_stockout"):
    return Plan("family-v2-test","EV-v2-test","vaccine_2_8",Asset("asset-test",.004,2,12,.9,0),
                42,180,90,5,"pulse","nominal",30,.05,.2,(Fault(code,30,50,1),))


def test_future_fault_cannot_change_temporal_inputs_or_current_labels():
    first = plan(); future = replace(first,faults=first.faults+(Fault("equipment_breakdown",100,20,1),))
    assert extract_temporal(simulate(first,SPECS),SPECS)==extract_temporal(simulate(future,SPECS),SPECS)
    assert hidden_labels(first)["injected_causes"]==hidden_labels(future)["injected_causes"]


def test_door_staff_twins_remain_identical_in_all_111_predictors():
    first = replace(plan("door_left_open"),ambiguity=True)
    assert extract_temporal(simulate(first,SPECS),SPECS)==extract_temporal(simulate(twin(first),SPECS),SPECS)
    assert hidden_labels(first)["injected_causes"] != hidden_labels(twin(first))["injected_causes"]


def test_subsumed_power_fault_is_not_magically_identifiable_even_with_temporal_inputs():
    first = plan(); both = replace(first,faults=first.faults+(Fault("power_outage",30,50,1),))
    assert simulate(first,SPECS)==simulate(both,SPECS)
    assert extract_temporal(simulate(first,SPECS),SPECS)==extract_temporal(simulate(both,SPECS),SPECS)
    assert hidden_labels(first)["injected_causes"]==["generator_fuel_stockout"]
    assert hidden_labels(both)["injected_causes"]==["generator_fuel_stockout","power_outage"]


@pytest.mark.parametrize("change",["extra","missing","reorder","infinite"])
def test_temporal_contract_is_independent_and_strict(change):
    frame = pd.DataFrame([extract_temporal(observation(),SPECS)],columns=TEMPORAL_FEATURES)
    if change=="extra": frame["cause"]="target"
    elif change=="missing": frame=frame.drop(columns="mains_unavailable_fuel_mean")
    elif change=="reorder": frame=frame[list(reversed(TEMPORAL_FEATURES))]
    else: frame.loc[0,"airflow_low_known_min"]=np.inf
    with pytest.raises(ValueError): validate_temporal(frame)


def test_temporal_preprocessing_fit_only_train_accepts_missing_and_unseen_category():
    row = extract_temporal(observation(),SPECS)
    train = pd.DataFrame([row]*40,columns=TEMPORAL_FEATURES)
    train["mains_unavailable_fuel_mean"]=np.linspace(.01,.8,40)
    train.loc[:4,"mains_unavailable_fuel_mean"]=np.nan
    truth = np.tile((np.arange(40)%2)[:,None],(1,11))
    model = make_temporal_pipeline()
    with threadpool_limits(limits=1):
        model.fit(train,truth)
        imputer = model.named_steps["observed_only"].named_transformers_["numeric"]
        before = imputer.statistics_.copy()
        test = train.copy(); test["product_id"]="UNSEEN"; test["mains_unavailable_fuel_mean"]=10000
        assert temporal_probabilities(model,test).shape==(40,11)
        assert np.array_equal(before,imputer.statistics_)


@pytest.mark.parametrize("role",list(data.ROLE_CONFIG))
def test_v2_role_replay_and_profile_definition(tmp_path,role):
    summary = data.create_role(tmp_path,role,20,20261014)
    audit,sets = data.verify_role(tmp_path,role,summary)
    assert audit["events"]==20 and audit["replays"]==2 and audit["future_prefix_checks"]==2
    assert len(sets[0])<=20 and len(sets[1])<=32
    with pytest.raises(ValueError): data.create_role(tmp_path,role,20,20261014)


def test_repeated_seed_reproduces_data_hashes_and_role_seeds_are_distinct(tmp_path):
    first = data.create_role(tmp_path/"one","train_stress",20,42)
    second = data.create_role(tmp_path/"two","train_stress",20,42)
    other = data.create_role(tmp_path/"two","validation_stress",20,42)
    assert first["file_sha256"]==second["file_sha256"]
    assert first["seed"]!=other["seed"]


@pytest.mark.filterwarnings("ignore:Label.*:UserWarning")
def test_end_to_end_v2_freezes_before_test_generation_and_does_not_replace_baseline(tmp_path,monkeypatch):
    baseline = tmp_path/"baseline"; baseline.mkdir()
    x = pd.DataFrame([{k:extract_temporal(observation(),SPECS)[k] for k in FEATURES}]*40,columns=FEATURES)
    truth = np.stack([np.arange(40)%(i+2)==0 for i in range(11)],axis=1).astype(int)
    model = make_pipeline("full","hgb")
    with threadpool_limits(limits=1): model.fit(x,truth)
    joblib.dump(model,baseline/"selected-experimental-model.joblib")
    import sklearn
    (baseline/"protocol.json").write_text(json.dumps({"target_order":list(TARGETS),"features_by_view":{"full":list(FEATURES)},"versions":{"scikit-learn":sklearn.__version__}}))
    (baseline/"selection-frozen.json").write_text(json.dumps({"selected":"full_hgb","model_sha256":evaluation.digest(baseline/"selected-experimental-model.joblib"),
        "protocol_sha256":evaluation.digest(baseline/"protocol.json"),"thresholds":{"full_hgb":[.5]*11}}))
    before = evaluation.digest(baseline/"selected-experimental-model.joblib")
    output = tmp_path/"experiment"
    original = evaluation.create_role
    def guarded(root,role,*args):
        if role in data.TEST:
            assert (output/"selection-frozen.json").exists()
            assert all((output/(name+".joblib")).exists() for name in evaluation.PROBES)
        return original(root,role,*args)
    monkeypatch.setattr(evaluation,"create_role",guarded)
    result = evaluation.run(output,baseline,train_per_profile=20,validation_per_profile=20,test_per_role=20,bootstrap=5)
    assert result["status"]=="complete" and result["promotion"] is False
    assert set(result["test"])==set(data.TEST)
    assert evaluation.digest(baseline/"selected-experimental-model.joblib")==before
    for probes in result["test"].values():
        assert all(p["screened"]["review_required_events"]==20 and p["screened"]["automatic_actions_allowed_events"]==0 for p in probes.values())
    with pytest.raises(ValueError): evaluation.run(output,baseline)
