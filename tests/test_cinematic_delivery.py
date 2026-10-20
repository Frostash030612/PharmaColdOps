"""Cinematic rendering boundaries and packaging helpers, not clinical evidence."""
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from serve_cinematic import upload_target
from finalize_cinematic import stamp


def test_upload_has_only_fifteen_fixed_video_slots(tmp_path):
    assert upload_target(tmp_path,'0')==tmp_path/'part-00.mp4'
    assert upload_target(tmp_path,'14')==tmp_path/'part-14.mp4'
    for bad in ['-1','15','../../credentials','0.mp4','1.5',None]:
        with pytest.raises((ValueError,TypeError)):
            upload_target(tmp_path,bad)


def test_small_geography_input_is_only_generalized_singapore_and_has_provenance():
    data=json.loads((ROOT/'media/cinematic/assets/singapore-outline.geojson').read_text())
    assert data['license']=='Public domain' and len(data['features'])==1
    feature=data['features'][0]
    assert feature['properties']=={'ADMIN':'Singapore','ADM0_A3':'SGP'}
    ring=feature['geometry']['coordinates'][0]
    assert ring[0]==ring[-1] and len(ring)>20
    assert all(103.5<lon<104.2 and 1.1<lat<1.6 for lon,lat in ring)
    assert len(data['source_sha256'])==64 and 'not a surveyed/current shoreline'in data['scope']


def test_subtitle_clock_retains_exact_user_scene_boundaries():
    assert [stamp(t)for t in [0,15,35,75,95,115,150]]==[
        '00:00:00,000','00:00:15,000','00:00:35,000','00:01:15,000',
        '00:01:35,000','00:01:55,000','00:02:30,000']


def test_staging_and_movie_do_not_target_application_state_or_use_voice_services():
    text=(ROOT/'media/cinematic/film.mjs').read_text()
    assert '/api/'not in text and '127.0.0.1:8080'not in text
    assert 'X-Render-Session'in text and 'X-Render-Part'in text
    score=(ROOT/'scripts/synthesize_cinematic_score.py').read_text()
    assert 'np.sin'in score and 'readframes('not in score
    assert 'requests.post'not in score and 'httpx.post'not in score


def test_final_packaging_verifies_actual_full_length_and_does_not_claim_camera_capture():
    source=(ROOT/'scripts/finalize_cinematic.py').read_text()
    assert 'frames!=4500'in source and "'real_camera_footage':False"in source
    assert 'NOT an actual capture or delivery specification'in source
    assert 'no actual'in source.lower() or 'not actual'in source.lower()
    assert "'submission_ready':False"in source
