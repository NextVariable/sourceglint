"""Repository identity supplies topic context without supplying claim truth."""
import json
from urllib.parse import parse_qs, urlparse

import pytest

from sourceglint.connectors._deep import issue_results
from sourceglint.connectors._http import HttpResponse

PLAN = {"time_window": {"start": "2026-09-05T00:00:00Z", "end": "2026-10-05T00:00:00Z"}}
QUERY = "Claude Code complaints"
ROOT = "https://github.com/anthropics/claude-code"


def response(value):
    return HttpResponse(200, body=json.dumps(value).encode())


@pytest.mark.parametrize("resolved,path,body,expected", [
    (True, ROOT, "The terminal freezes after I press enter.", True),
    (True, ROOT, "Claude Code freezes.", True),
    (False, ROOT, "The terminal freezes after I press enter.", True),
    (False, ROOT, "Claude Code freezes.", True),
    (True, "https://github.com/unrelated/game", "Claude Code freezes.", False),
    (True, ROOT + "-unrelated", "Claude Code freezes.", False),
    (True, "https://github.com.evil.example/anthropics/claude-code", "Claude Code freezes.", False),
])
def test_resolved_repository_context_and_external_scope_boundaries(resolved,path,body,expected):
    class Client:
        def request(self,url,**kwargs):
            if '/search/repositories?' in url:
                return response({'items':[{'name':'claude-code','full_name':'anthropics/claude-code','fork':False}]} if resolved else {'items':[]})
            if 'created:<' in parse_qs(urlparse(url).query).get('q',[''])[0]:
                return response({'items':[]})
            return response({'items':[{'id':1,'html_url':path+'/issues/1','title':'[Bug] Frozen terminal','body':body,'created_at':'2026-09-20T00:00:00Z','comments':0}]})
    rows=issue_results(Client(),QUERY,PLAN,{'query':QUERY},{},[])
    assert bool(rows) is expected
    if rows:
        assert rows[0].raw_metadata['retrieval_scope']==('repo:anthropics/claude-code' if resolved else 'global_subject_search')


@pytest.mark.parametrize('repo_name',['claude-code','claude_code','claudecode'])
def test_exact_repository_name_alias_supplies_context(repo_name):
    root='https://github.com/anthropics/'+repo_name
    class Client:
        def request(self,url,**kwargs):
            if '/search/repositories?' in url:
                return response({'items':[{'name':repo_name,'full_name':'anthropics/'+repo_name}]})
            if 'created:<' in parse_qs(urlparse(url).query).get('q',[''])[0]:
                return response({'items':[]})
            return response({'items':[{'id':1,'html_url':root+'/issues/1','title':'Frozen terminal','body':'Pressing enter hangs.','created_at':'2026-09-20T00:00:00Z'}]})
    rows=issue_results(Client(),QUERY,PLAN,{'query':QUERY},{},[])
    assert len(rows)==1
    assert rows[0].raw_metadata['retrieval_scope']=='repo:anthropics/'+repo_name


def test_recent_reply_on_old_scoped_issue_keeps_topic_context_and_own_date():
    class Client:
        def request(self,url,**kwargs):
            if '/search/repositories?' in url:
                return response({'items':[{'name':'claude-code','full_name':'anthropics/claude-code'}]})
            if '/comments?' in url:
                return response([{'id':42,'html_url':ROOT+'/issues/9#issuecomment-42','body':'Still broken on the current version.','created_at':'2026-09-22T00:00:00Z'}])
            if 'created:<' in parse_qs(urlparse(url).query).get('q',[''])[0]:
                return response({'items':[{'id':9,'html_url':ROOT+'/issues/9','title':'Terminal freezes','body':'Pressing enter hangs.','created_at':'2026-08-10T00:00:00Z','updated_at':'2026-09-22T00:00:00Z','comments':1}]})
            return response({'items':[]})
    rows=issue_results(Client(),QUERY,PLAN,{'query':QUERY},{},[])
    assert len(rows)==1 and rows[0].source_type=='comment'
    assert rows[0].published_at=='2026-09-22T00:00:00Z'
    assert rows[0].raw_metadata['parent_published_at']=='2026-08-10T00:00:00Z'
    assert rows[0].raw_metadata['retrieval_scope']=='repo:anthropics/claude-code'
