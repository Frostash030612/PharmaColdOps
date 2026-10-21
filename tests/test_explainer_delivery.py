"""Offline source packaging, not independent clinical or human review evidence."""
import importlib.util
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('explainer_finalizer',ROOT/'scripts/finalize_explainer.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_standalone_preview_inlines_its_own_animation_without_external_modules():
    html=module.inline_preview()
    assert '<html lang="en">'in html and 'function drawFrame'in html and 'const STORY'in html
    assert not re.search(r'^import ',html,re.M)
    assert 'export const 'not in html and 'export function 'not in html
    assert not re.search(r'<script[^>]+src=',html)
    assert 'fetch('not in html and 'XMLHttpRequest'not in html and 'WebSocket'not in html
    assert 'window.seek=function'in html


def test_preview_does_not_call_or_mutate_the_project_api():
    for name in ['scene.mjs','story.mjs','index.html']:
        text=(ROOT/'media/explainer'/name).read_text(encoding='utf-8')
        assert 'http://127.0.0.1:8080'not in text
        assert '/api/'not in text and 'sessionStorage'not in text and 'localStorage'not in text
    assert 'not a live system recording'in (ROOT/'scripts/finalize_explainer.py').read_text()


def test_original_score_source_contains_no_recordings_or_voice_service():
    text=(ROOT/'scripts/synthesize_explainer_score.py').read_text()
    assert 'np.sin'in text and "wave.open(str(args.output),'wb')"in text
    assert not re.search(r'^import (?:requests|httpx)|^from (?:requests|httpx)',text,re.M)
    assert 'readframes('not in text and 'requests.post'not in text
