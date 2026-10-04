"""Regression cases for lost context, copied reporting and failed assessment."""
import json
from dataclasses import replace
from sourceglint.pipeline.deduplication import deduplicate
from sourceglint.intelligence.dtos import PreparedEvidence, ValidatedCluster
from sourceglint.intelligence.features import derive_features
from sourceglint.intelligence.preparation import model_payloads
from sourceglint.intelligence.contradiction import _degraded_assessment
from sourceglint.insights.preparation import prepare_signals
from sourceglint.connectors._captions import fetch_captions
from sourceglint.connectors._http import HttpResponse
from sourceglint.excerpts import select_excerpt


def test_degraded_contradiction_does_not_become_support_or_facts():
    cluster = ValidatedCluster('c', 'claim', 'claim', ('a', 'b'), .9)
    assessment = _degraded_assessment(cluster, 'offline')
    assert assessment.supporting_evidence_ids == ()
    prepared, warnings = prepare_signals([{'signal_id': 's', 'evidence_ids': ['a','b'], 'contradiction_assessed': False}], {})
    assert not prepared
    assert any('unassessed' in w for w in warnings)


def test_explicit_empty_support_is_not_silently_replaced_by_all_evidence():
    prepared, _ = prepare_signals([{'signal_id': 's', 'evidence_ids': ['a'], 'supporting_evidence_ids': []}], {'a': {'snippet': 'Counterexample'}})
    assert prepared[0].supporting_evidence_summaries == ()


def test_same_source_body_enrichment_preserves_original_identity_and_quote():
    short = {'evidence_id': 'a', 'url': 'https://example.com/post', 'snippet': 'Real quote', 'published_at': '2026-10-01'}
    rich = {**short, 'evidence_id': 'b', 'content': 'Real quote. Important counterexample.'}
    result = deduplicate([short, rich])
    assert result.kept[0]['content'] == rich['content']
    assert result.kept[0]['evidence_id'] == 'a'
    assert result.kept[0]['snippet'] == 'Real quote'
    assert result.provenance['a'].retrieval_count == 2
    conflicting = {**rich, 'published_at': '2026-09-01'}
    assert not deduplicate([short, conflicting]).kept[0].get('content')


def test_copy_on_another_domain_does_not_add_independent_corroboration():
    cluster = ValidatedCluster('c', 'claim', 'claim', ('a', 'b', 'd'), .9)
    copy = 'Original reporting contains unique technical observations. ' * 8
    evidence = {i: PreparedEvidence(i, 'web', 'page', 'current', url=u, content=text) for i,u,text in [('a','https://vendor.example/post',copy),('b','https://mirror.example/post',copy),('d','https://third.example/post','A separate independent report about another experiment.') ]}
    features = derive_features(cluster, evidence)
    assert features.independent_source_count == 2
    assert len(features.unique_domains) == 3
    assert 'shared_text_origin' in features.independence_kinds


def test_near_copy_footer_does_not_add_origin_but_distinct_body_does():
    body = ' '.join('technical-observation-'+str(i) for i in range(100))
    cluster = ValidatedCluster('c', 'claim', 'claim', ('a','b'), .9)
    a = PreparedEvidence('a','web','page','current',url='https://one.example',content=body)
    b = replace(a, evidence_id='b',url='https://two.example',content=body+' Copyright publisher.')
    assert derive_features(cluster, {'a':a,'b':b}).independent_source_count == 1
    b = replace(b,content='This author conducted an entirely different test with new observations.')
    assert derive_features(cluster, {'a':a,'b':b}).independent_source_count == 2


def test_middle_topic_evidence_reaches_model_under_large_batch_budget():
    body = 'Intro filler. '*500 + 'Credential exposure: tokens can leak to an attacker.' + 'End filler. '*500
    items = [PreparedEvidence(str(i),'web','page','current',content=body) for i in range(100)]
    payloads = model_payloads(items, topic='credential exposure tokens')
    assert all('tokens can leak' in p['content'] for p in payloads)
    assert sum(len(p['content']) for p in payloads) <= 48000
    assert 'middle omitted' in payloads[0]['content']
    assert 'tokens can leak' in select_excerpt(body*5,'credential exposure',12000)


def test_caption_track_failure_tries_working_alternative_and_records_failure():
    calls = []
    class Client:
        def request(self,url,**kwargs):
            calls.append(url)
            if url.endswith('broken'): raise TimeoutError()
            return HttpResponse(200, body=json.dumps({'events':[{'segs':[{'utf8':'working caption'}]}]}).encode())
    tracks = {'subtitles':{'en':[{'ext':'json3','url':'https://www.youtube.com/broken'},{'ext':'json3','url':'https://www.youtube.com/working'}]}}
    text, meta = fetch_captions(Client(),tracks)
    assert 'working caption' in text
    assert len(calls) == 2
    assert meta['caption_failures'][0]['error_type'] == 'TimeoutError'


def test_caption_failure_budget_is_bounded():
    calls = []
    class Client:
        def request(self,url,**kwargs):
            calls.append(url)
            raise TimeoutError()
    tracks = [{'ext':'json3','url':'https://www.youtube.com/broken'}]*2
    _,meta = fetch_captions(Client(),{'subtitles':{'en':tracks,'en-US':tracks},'automatic_captions':{'en':tracks}})
    assert len(calls) == 4
    assert meta['transcript_status'] == 'unavailable'


def test_enriched_body_invalidates_cache_without_changing_canonical_ids():
    from sourceglint.intelligence.cache import build_cache_key
    common = dict(task='clustering',prompt_version='v1',model_id='test',evidence_ids=['same-id'],research_context={})
    before = build_cache_key(**common,input_payload={'content':'short body'})
    after = build_cache_key(**common,input_payload={'content':'full body with counterexample'})
    assert before != after
    assert before == build_cache_key(**common,input_payload={'content':'short body'})


def test_insight_support_uses_same_copy_rules_as_signal_features():
    from sourceglint.insights.support import distinct_source_count
    body = 'Original reporting contains unique technical observations. ' * 8
    evidence = {'a':{'url':'https://vendor.example/post','content':body}, 'b':{'url':'https://mirror.example/post','content':body}}
    assert distinct_source_count(['a','b'], evidence) == 1


def test_unassessed_signal_pipeline_never_calls_fact_model():
    from sourceglint.insights.pipeline import run_insight_pipeline
    class Model:
        model_id = 'must-not-run'
        def complete_structured(self, **kwargs):
            raise AssertionError('Unassessed evidence reached fact generation')
    result = run_insight_pipeline([{'signal_id':'s','evidence_ids':['a'],'contradiction_assessed':False}], {'a':{'snippet':'A claim'}}, Model())
    assert not result.insights
    assert any('unassessed' in w for w in result.warnings)
