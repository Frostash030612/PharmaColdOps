"""M6 response semantics and provenance without manufacturing human judgements."""
from contextlib import nullcontext

import pytest

from knowledge_graph import qa


@pytest.mark.parametrize('url', ['https://example.org/source', 'http://example.org/source'])
def test_recorded_public_reference_metadata_is_exposed_without_validating_product_limits(url):
    item = qa._reg_evidence([{'clause_id':'R-TEST', 'title':'Unit reference', 'clause':'1',
                             'summary':'A principle, not a medicine limit.', 'source_url':url, 'verified':'document-level check'}])[0]
    assert item['source_url'] == url
    assert item['verified'] == 'document-level check'
    assert 'not_product_stability_validation' in item['reference_scope']
    assert 'A principle' in item['summary']


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///tmp/source', 'https://user:password@example.org/source', 'https://[invalid'])
def test_reference_metadata_does_not_publish_unsafe_or_credentialled_links(url):
    assert 'source_url' not in qa._reference_info({'source_url':url})


def test_existing_product_without_references_is_insufficient_not_missing(monkeypatch):
    product = {'storage_min_c':2, 'storage_max_c':8, 'allowable_duration_min':30,
               'mkt_threshold_c':12, 'freeze_sensitive':True, 'retestable':False}
    monkeypatch.setattr(qa, '_connect', lambda: nullcontext(object()))
    monkeypatch.setattr(qa, '_run', lambda *args, **kwargs: [{'p':product, 'rules':[]}])
    result = qa.product_requirements('unit-product')
    assert result['status'] == 'insufficient_evidence'
    assert result['evidence'] == []
    assert 'engineering assumptions' in result['answer']
    assert 'not manufacturer-approved' in result['answer']


def test_missing_product_is_still_missing(monkeypatch):
    monkeypatch.setattr(qa, '_connect', lambda: nullcontext(object()))
    monkeypatch.setattr(qa, '_run', lambda *args, **kwargs: [])
    assert qa.product_requirements('missing')['status'] == 'no_case'


def test_http_response_keeps_optional_reference_fields_and_omits_absent_ones(monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app
    from api import service
    evidence=qa._reg_evidence([{'clause_id':'R-HTTP-UNIT', 'title':'Unit source', 'source_url':'https://example.org/reference'}])
    evidence.append({'node_type':'Product','node_id':'unit-product','summary':'unit record'})
    monkeypatch.setattr(service,'qa_view',lambda req:{'status':'ok','answer':'unit HTTP serialization','evidence':evidence})
    response=TestClient(app).post('/api/qa',json={'question_type':'product_requirements','product_id':'unit-product'})
    assert response.status_code==200
    nodes=response.json()['evidence']
    assert nodes[0]['source_url']=='https://example.org/reference'
    assert nodes[0]['reference_scope'].endswith('not_product_stability_validation')
    assert set(nodes[1])=={'node_type','node_id','summary'}
