"""Recording the Skill profile must retain the actual native connector lane."""
import contextlib
import io
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

from sourceglint.application import api, runtime
from sourceglint.host_stdio import StdioHostSource


def test_registry_alone_records_native_routes_without_redirecting_them_to_host(monkeypatch,tmp_path):
    root=Path(__file__).resolve().parents[2]
    native_calls=[]
    markers={name:object() for name in ['reddit','hacker_news','github','youtube']}
    def native(name,plan):
        native_calls.append(name)
        return markers[name]
    def run(query,**kwargs):
        factory=kwargs['adapter_factory']
        for source in kwargs['sources']:
            adapter=factory(source['name'],{})
            if source['name']=='host_web_search':
                assert isinstance(adapter,StdioHostSource)
            else:
                assert adapter is markers[source['name']]
        return SimpleNamespace(diagnostics={},status=SimpleNamespace(value='NO_EVIDENCE'),brief_markdown='Synthetic recording check',to_dict=lambda:{'status':'NO_EVIDENCE'})
    monkeypatch.setattr(runtime,'default_adapter_factory',native)
    monkeypatch.setattr(api,'run_sourceglint',run)
    monkeypatch.setattr(sys,'argv',['run_host_evaluation.py','--query','MCP security','--name','recording-check','--directory',str(tmp_path),'--as-of','2026-10-05T00:00:00Z','--registry',str(root/'config/sources-hybrid.yaml')])
    with contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(str(root/'scripts/run_host_evaluation.py'),run_name='__main__')
    assert set(native_calls)==set(markers)
    assert (tmp_path/'recording-check.json').exists()
