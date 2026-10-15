"""Offline regression tests for bounded discovery, scheduling and digest evidence."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from email import message_from_string
from email.header import decode_header, make_header
import json
from types import SimpleNamespace

import numpy as np
from omegaconf import OmegaConf, open_dict
import pytest
import tiktoken

from tests.canned_responses import make_sample_paper, make_sample_corpus, make_stub_smtp
from zotero_arxiv_daily.analysis import PaperAnalysis, parse_analysis, select_paper_input, safe_url, extract_resource_links
from zotero_arxiv_daily.construct_email import render_email, render_email_text, email_subject
from zotero_arxiv_daily.discovery import DiscoveryEngine, openalex_paper
from zotero_arxiv_daily.protocol import CorpusPaper
from zotero_arxiv_daily.recommendation import (
    TOPICS, RecommendationState, identity_keys, unique_papers, select_daily, classify_candidates,
)


def analysis_json(**updates):
    value = dict(summary_en="An English overview of the supplied paper.", summary="中文简介", problem="研究问题", method="核心方法", contributions=["作者贡献"],
                 experiments=[], author_limitations=[], inferred_insights=["分析推断"],
                 relation="direct", relation_reason="用于VLN和建图", topics=["VLN"])
    value.update(updates)
    return json.dumps(value, ensure_ascii=False)


def client_response(content=None, error=None, calls=None):
    def create(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if error:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_structured_analysis_one_call_and_summary():
    paper = make_sample_paper()
    calls = []
    analysis = paper.generate_analysis(client_response(analysis_json(), calls=calls), {"generation_kwargs": {}})
    assert analysis.status == "ok" and paper.tldr == "中文简介" and len(calls) == 1
    assert analysis.summary_en == "An English overview of the supplied paper."
    assert "summary_en" in calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("english", [None, "", "  ", [], 42])
def test_missing_english_summary_is_an_explicit_analysis_failure(english):
    paper = make_sample_paper()
    assert paper.generate_analysis(client_response(analysis_json(summary_en=english)), {}).status == "failed"


def test_bilingual_sections_in_html_and_plain_text():
    paper = make_sample_paper(analysis=PaperAnalysis(summary="中文简介", summary_en="English <overview> & evidence"))
    for rendered in (render_email([paper]), render_email_text([paper])):
        assert rendered.index("英文简介") < rendered.index("中文简介")
    assert "English &lt;overview&gt; &amp; evidence" in render_email([paper])
    assert "English <overview> & evidence" in render_email_text([paper])


@pytest.mark.parametrize("content", [None, "", "not json", "[]", '{}', analysis_json(method=None)])
def test_analysis_failure_falls_back(content):
    paper = make_sample_paper()
    result = paper.generate_analysis(client_response(content), {})
    assert result.status == "failed" and paper.tldr == paper.abstract
    assert "生成失败" in render_email([paper])


def test_analysis_api_failure_and_no_source():
    paper = make_sample_paper(abstract="", full_text=None)
    assert paper.generate_analysis(client_response(error=RuntimeError()), {}).status == "failed"
    paper = make_sample_paper()
    assert paper.generate_analysis(client_response(error=RuntimeError()), {}).summary == paper.abstract


def test_experimental_numbers_require_exact_source_and_matching_number():
    result = parse_analysis(analysis_json(experiments=[
        {"text": "成功率82.5%", "evidence": "Success is 82.5%."},
        {"text": "成功率99.9%", "evidence": "Success is 82.5%."},
        {"text": "成功率82.5%", "evidence": "Invented result 82.5%."},
    ]), "Methods\nSuccess is 82.5%.", "excerpts")
    assert len(result.experiments) == 1 and result.omitted_findings == 2


def test_input_labels_and_section_coverage():
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert select_paper_input("Title", "Abstract", None)[1] == "abstract"
    assert select_paper_input("Title", "Abstract", "Short body")[1] == "full_text"
    body = "\n".join(f"## {section}\n{section} evidence " + "word " * 2000
                      for section in ["Methods", "Experiments", "Discussion", "Conclusion"])
    source, level = select_paper_input("Title", "Abstract", body, 1200)
    assert level == "excerpts" and len(enc.encode(source)) <= 1200
    assert all(name in source for name in ["Methods", "Experiments", "Discussion", "Conclusion"])
    plain, level = select_paper_input("Title", "Abstract", "word " * 5000 + "THE END", 700)
    assert "THE END" in plain and level == "excerpts"


@pytest.mark.parametrize("budget", [0, 255, -1, True, "12000"])
def test_invalid_token_budget(budget):
    with pytest.raises(ValueError):
        select_paper_input("Title", "Abstract", "Text", budget)


def test_safe_links_and_escaping():
    paper = make_sample_paper(title='<script>alert("x")</script>', authors=['A & B'], pdf_url="javascript:alert(1)", url="data:text/html,foo")
    html = render_email([paper])
    assert "<script>" not in html and "&lt;script&gt;" in html and "A &amp; B" in html
    assert "javascript:" not in html and "data:text/html" not in html and 'href="None"' not in html
    assert safe_url("https://user:pass@example.org") is None
    links = extract_resource_links(r"Code: \url{https://github.com/org/repo}. Project: https://example.org/project.")
    assert links == [("Code", "https://github.com/org/repo"), ("Project", "https://example.org/project")]


def test_timezone_and_plain_text_and_empty_subject():
    moment = datetime(2026, 10, 14, 20, tzinfo=timezone.utc)
    assert "2026-10-15｜1篇" in email_subject(1, date=moment)
    assert "暂无符合条件" in email_subject(0, date=date(2026, 10, 15))
    p = make_sample_paper(analysis=PaperAnalysis(summary="中文简介"), origin="internal", published_date="2018")
    assert "库内精读" in render_email_text([p]) and "2018" in render_email([p])


def candidates():
    return [make_sample_paper(title=f"{topic} paper {i}", url=f"https://example.org/{n}/{i}",
                             primary_topic=topic, origin="internal" if i == 0 and n < 3 else "external",
                             score=9 - i / 100, priority="high")
            for n, topic in enumerate(TOPICS) for i in range(12)]


def test_15_papers_12_external_3_internal_with_soft_topics():
    selected = select_daily(candidates())
    assert len(selected) == 15
    assert Counter(p.origin for p in selected) == {"external": 12, "internal": 3}
    assert Counter(p.primary_topic for p in selected) == dict(zip(TOPICS, [5, 4, 3, 3]))


def test_shortage_quality_priority_and_origin_caps():
    pool = [p for p in candidates() if p.primary_topic != "SLAM"]
    selected = select_daily(pool)
    assert len(selected) == 15 and all(p.primary_topic != "SLAM" for p in selected)
    weak = make_sample_paper(title="weak", primary_topic="SLAM", origin="external", priority="skip", score=10)
    assert weak not in select_daily([weak] + pool)
    assert len(select_daily([p for p in pool if p.origin == "external"])) == 12
    medium = make_sample_paper(title="medium", url="https://example.org/medium", primary_topic="VLN", priority="medium", score=10)
    high = make_sample_paper(title="high", url="https://example.org/high", primary_topic="SLAM", priority="high", score=1)
    assert select_daily([medium, high], max_total=1) == [high]


def test_dedup_doi_versions_and_transitive_aliases():
    first = make_sample_paper(title="Old Title", doi="https://doi.org/10.1234/ABC", arxiv_id="2401.12345v2")
    second = make_sample_paper(title="Formal Title", source="openalex", doi="10.1234/abc")
    third = make_sample_paper(title="Third Title", arxiv_id="2401.12345v8")
    assert len(unique_papers([first, second, third])) == 1
    assert unique_papers([first, second, third], {"arxiv:2401.12345"}) == []


def test_state_internal_rotation_and_no_private_text(tmp_path):
    state = RecommendationState(tmp_path / "state.json")
    now = datetime.now(timezone.utc)
    old, new = candidates()[:2]
    old.origin = new.origin = "internal"
    state.mark_sent([old], now - timedelta(days=100))
    assert state.internal_candidates([old, new], now) == [new]
    state.mark_sent([new], now - timedelta(days=1))
    assert state.internal_candidates([old, new], now) == [old]
    ext = make_sample_paper(full_text="PRIVATE_BODY", tldr="PRIVATE_TLDR")
    state.cache_candidates([ext, old])
    state.save()
    assert "PRIVATE_BODY" not in state.path.read_text() and "PRIVATE_TLDR" not in state.path.read_text()
    reloaded = RecommendationState(state.path)
    assert reloaded.sent_keys() >= identity_keys(old)


def test_corrupt_state_does_not_reset_history(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version":99}')
    with pytest.raises(ValueError):
        RecommendationState(path)


def test_triage_is_bounded_and_rejects_bad_output():
    pool = candidates()[:2]
    response = json.dumps([dict(index=i, topic="VLN", priority="high", reason="相关") for i in range(2)])
    assert len(classify_candidates(pool, client_response(response), {})) == 2
    assert classify_candidates(pool, client_response('[]'), {}) == []


@pytest.mark.parametrize("publication_type", ["article", "journal-article", "conference-paper", "proceedings-article"])
def test_openalex_metadata_and_no_age_cutoff(publication_type):
    item = dict(id="https://openalex.org/W1", display_name="Classic Paper", type="article", is_retracted=False,
                open_access={"is_oa": True}, publication_date="2008-01-01", doi="https://doi.org/10.1234/test",
                abstract_inverted_index={"An": [0], "abstract": [1]}, authorships=[],
                best_oa_location={"pdf_url": "https://example.org/paper.pdf"})
    item["type"] = publication_type
    paper = openalex_paper(item, "SLAM")
    assert paper.published_date == "2008-01-01" and paper.abstract == "An abstract"
    item["is_retracted"] = True
    assert openalex_paper(item, "SLAM") is None


def test_multipart_subject_and_refusal(config, monkeypatch):
    import smtplib
    from zotero_arxiv_daily.utils import send_email
    sent = []
    monkeypatch.setattr(smtplib, "SMTP", make_stub_smtp(sent))
    send_email(config, "<p>中文</p>", text="中文纯文本", subject="测试｜15篇")
    msg = message_from_string(sent[0][2])
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.get_payload()] == ["text/plain", "text/html"]
    assert str(make_header(decode_header(msg["Subject"]))) == "测试｜15篇"
    assert msg.get_payload()[0].get_payload(decode=True).decode() == "中文纯文本"

    class Refused(make_stub_smtp(sent)):
        def sendmail(self, *args):
            return {"test@example.com": (550, b"refused")}
    monkeypatch.setattr(smtplib, "SMTP", Refused)
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        send_email(config, "test")


@pytest.mark.parametrize("smtp_failure", [False, True])
def test_new_daily_pipeline_and_delivery_history(config, monkeypatch, tmp_path, smtp_failure):
    import zotero_arxiv_daily.daily as daily
    with open_dict(config):
        config.recommendation.enabled = True
        config.recommendation.state_path = str(tmp_path / "state.json")
    library = [CorpusPaper(title=f"Library {i}", abstract=f"Spatial memory evidence {i}",
                           added_date=datetime(2026, 1, 1), paths=[], zotero_key=f"KEY{i}") for i in range(3)]
    external = [p for p in candidates() if p.origin == "external"]
    monkeypatch.setattr(daily.DiscoveryEngine, "discover", lambda self: external)
    def triage(papers, *args):
        for paper in papers:
            if paper.origin == "internal":
                paper.primary_topic = "SLAM"
            paper.priority = "high"
            paper.recommendation_reason = "与研究方向相关"
        return papers
    monkeypatch.setattr(daily, "classify_candidates", triage)
    hydrated = []
    monkeypatch.setattr(daily, "hydrate_paper", lambda paper, config: hydrated.append(paper))
    monkeypatch.setattr("zotero_arxiv_daily.protocol.Paper.generate_affiliations", lambda *args: [])
    class Ranker:
        def rerank(self, papers, corpus):
            return papers
        def get_similarity_score(self, left, right):
            return np.ones((len(left), len(right)))
    sent = []
    def send(*args, **kwargs):
        if smtp_failure:
            raise RuntimeError("SMTP rejected")
        sent.append((args, kwargs))
    monkeypatch.setattr(daily, "send_email", send)
    executor = SimpleNamespace(config=config, fetch_zotero_corpus=lambda: library,
                               filter_corpus=lambda papers: papers, reranker=Ranker(),
                               openai_client=client_response(analysis_json()))
    if smtp_failure:
        with pytest.raises(RuntimeError):
            daily.run_recommendations(executor)
    else:
        daily.run_recommendations(executor)
        assert len(sent) == 1 and len(hydrated) == 15
        assert "库内精读3篇" in sent[0][0][1]
        assert "text" in sent[0][1] and "15篇" in sent[0][1]["subject"]
        # A second manual run must not spend more model calls or send more papers.
        daily.run_recommendations(executor)
        assert len(sent) == 1 and len(hydrated) == 15
    history = RecommendationState(config.recommendation.state_path).data["history"]
    assert len(history) == (0 if smtp_failure else 15)


def test_discovery_failure_uses_cache_and_does_not_advance_cursor(config, monkeypatch, tmp_path):
    state = RecommendationState(tmp_path / "state.json")
    with open_dict(config):
        config.recommendation.external_sources = ["openalex"]
    engine = DiscoveryEngine(config, state)
    monkeypatch.setattr(engine, "_openalex", lambda *args: (_ for _ in ()).throw(RuntimeError("offline")))
    assert engine.discover() == [] and state.data["offsets"] == {}


def test_arxiv_historical_pagination_does_not_revisit_first_page(config, monkeypatch, tmp_path):
    import zotero_arxiv_daily.discovery as discovery
    observed = []
    class Client:
        def __init__(self, **kwargs):
            pass
        def results(self, search, offset=0):
            observed.append((search.max_results, offset, search.query))
            return iter([])
    monkeypatch.setattr(discovery.arxiv, "Client", Client)
    engine = DiscoveryEngine(config, RecommendationState(tmp_path / "state.json"))
    engine._arxiv("VLN", discovery.QUERIES["VLN"], 30, 30)
    assert observed[0][:2] == (60, 30)
    assert "submittedDate" not in observed[0][2]
