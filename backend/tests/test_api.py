import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app import main, knowledge

client = TestClient(main.app)

@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    main.recent.clear()


def mock_model(monkeypatch, answer, code=200):
    monkeypatch.setenv('LLM_API_KEY', 'test-only-not-a-real-key')
    captured = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            captured.append(kwargs['json'])
            return httpx.Response(code, json={'choices':[{'message':{'content':json.dumps(answer, ensure_ascii=False)}}]}, request=httpx.Request('POST', url))
    monkeypatch.setattr(main.httpx, 'AsyncClient', FakeClient)
    return captured


def answer(**overrides):
    return {'textbook_facts':[], 'suggestions':'先在教练现场指导下练习平衡。', 'limitations':'仅供教学参考。', 'citation_ids':[], **overrides}


def test_missing_key():
    assert client.get('/api/status').json()['connection'] == 'not_configured'
    r=client.post('/api/chat',json={'messages':[{'role':'user','content':'你好'}]})
    assert r.status_code == 503
    assert 'LLM_API_KEY' in r.json()['detail']


def test_empty_pending_sources_excluded(monkeypatch):
    monkeypatch.setattr(knowledge,'sources',lambda:[{'verification_status':'pending','content':'未核验内容'}])
    assert knowledge.retrieve('未核验') == []

def test_actual_source_metadata():
    found=knowledge.retrieve('单足侧蹬冰')
    assert any(s['id']=='B02-93' and s['pages']=='原PDF第93页／印刷79页' and s['verification_status']=='pending' for s in found)
    assert any(s['id']=='B03-39' for s in knowledge.retrieve('刀齿蹬冰'))
    assert any(s['id']=='L08' for s in knowledge.retrieve('L08'))


def test_verified_retrieval(monkeypatch):
    # Synthetic fixture, never shipped as actual textbook knowledge.
    source={'id':'fixture','title':'测试教材','authors':'测试','pages':'PDF 91–93','source_type':'测试摘要','verification_status':'verified','content':'内刃测试摘要'}
    monkeypatch.setattr(knowledge,'sources',lambda:[source])
    found=knowledge.retrieve('内刃')
    assert found[0]['title']=='测试教材' and found[0]['pages']=='PDF 91–93'
    assert knowledge.retrieve('完全无关') == []


def test_chinese_and_multiturn_mock(monkeypatch):
    monkeypatch.setattr(main,'retrieve',lambda _, **kwargs: [])
    captured=mock_model(monkeypatch,answer())
    messages=[{'role':'user','content':'如何练习平衡？'},{'role':'assistant','content':'先在教练现场指导下练习平衡。'},{'role':'user','content':'那下一步呢？'}]
    r=client.post('/api/chat',json={'messages':messages})
    assert r.status_code==200
    assert captured[0]['messages'][1:]==messages
    assert r.json()['citations']==[]
    assert '暂无' not in r.json()['suggestions']
    assert '没有可用的已核验教材' in r.json()['limitations']


@pytest.mark.parametrize('data',[answer(citation_ids=['invented']),answer(suggestions='参考《伪造书》PDF 42页'),answer(textbook_facts=['伪造事实'])])
def test_reject_fabricated_citations(monkeypatch,data):
    mock_model(monkeypatch,data)
    assert client.post('/api/chat',json={'messages':[{'role':'user','content':'给出出处'}]}).status_code==502


def test_verified_citation_metadata(monkeypatch):
    source={'id':'fixture','title':'测试书','authors':'测试作者','pages':'PDF 39','source_type':'测试','verification_status':'verified','content':'测试事实'}
    monkeypatch.setattr(main,'retrieve',lambda _, **kwargs: [source])
    mock_model(monkeypatch,answer(textbook_facts=['测试事实'],citation_ids=['fixture']))
    r=client.post('/api/chat',json={'messages':[{'role':'user','content':'测试'}]})
    assert r.status_code==200 and r.json()['citations'][0]['pages']=='PDF 39'


@pytest.mark.parametrize('code,expected',[(401,502),(403,502),(429,429),(500,502)])
def test_upstream_errors(monkeypatch,code,expected):
    mock_model(monkeypatch,answer(),code)
    assert client.post('/api/chat',json={'messages':[{'role':'user','content':'你好'}]}).status_code==expected


def test_request_limits(monkeypatch):
    mock_model(monkeypatch,answer())
    for _ in range(12):
        assert client.post('/api/chat',json={'messages':[{'role':'user','content':'你好'}]}).status_code==200
    assert client.post('/api/chat',json={'messages':[{'role':'user','content':'你好'}]}).status_code==429
    assert client.post('/api/chat',json={'messages':[{'role':'user','content':'a'*6001}]}).status_code==422


def test_timeout(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY','test-only')
    class TimeoutClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr(main.httpx,'AsyncClient',TimeoutClient)
    assert client.post('/api/chat',json={'messages':[{'role':'user','content':'你好'}]}).status_code==504


def test_pending_citation_boundary(monkeypatch):
    source=knowledge.sources()[3]
    monkeypatch.setattr(main,'retrieve',lambda _, **kwargs: [source])
    mock_model(monkeypatch,answer(textbook_facts=['摘要介绍单足侧蹬冰。'],citation_ids=[source['id']]))
    r=client.post('/api/chat',json={'messages':[{'role':'user','content':'单足侧蹬冰'}]})
    assert r.status_code==200
    assert r.json()['citations'][0]['verification_status']=='pending'
    assert '仍待专业教师审核' in r.json()['limitations']
