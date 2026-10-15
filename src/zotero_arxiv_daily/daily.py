"""Daily discovery + library review pipeline, independent of the legacy RSS mode."""

from datetime import datetime, timezone

import numpy as np
from loguru import logger

from .analysis import safe_url
from .construct_email import report_date, render_email, render_email_text, email_subject
from .discovery import DiscoveryEngine, hydrate_paper
from .protocol import Paper
from .policy import apply_daily_policy
from .recommendation import (
    TOPICS, RecommendationState, all_keys, classify_candidates,
    identity_keys, normalize_arxiv, select_daily, title_key, unique_papers,
)
from .utils import send_email


def corpus_to_paper(item):
    url = safe_url(item.url)
    if not url and item.doi:
        url = f"https://doi.org/{item.doi}"
    return Paper(
        source="zotero", title=item.title, authors=item.authors or [], abstract=item.abstract,
        url=url or "", origin="internal", zotero_key=item.zotero_key,
        doi=item.doi, arxiv_id=normalize_arxiv(item.url), published_date=item.published_date,
    )


def _rank_internal(papers, corpus, reranker):
    # Exclude a paper's own abstract (and exact duplicate entries) from similarity.
    weights = 1 / (1 + np.log10(np.arange(len(corpus)) + 1))
    ordered = sorted(corpus, key=lambda c: c.added_date, reverse=True)
    matrix = reranker.get_similarity_score([p.abstract for p in papers], [c.abstract for c in ordered])
    for paper, similarities in zip(papers, matrix):
        masked = weights.copy()
        for i, entry in enumerate(ordered):
            if identity_keys(paper) & identity_keys(corpus_to_paper(entry)):
                masked[i] = 0
        paper.score = float(np.dot(similarities, masked) / masked.sum() * 10) if masked.sum() else 0.0
    return sorted(papers, key=lambda p: (getattr(p, "review_count", 0) == 0, p.score), reverse=True)


def _shortlist(papers, per_topic):
    # Keep each topic represented before costly LLM triage.
    selected = []
    for topic in TOPICS:
        selected.extend([p for p in papers if p.primary_topic == topic][:per_topic])
    return selected


def run_recommendations(executor):
    config = apply_daily_policy(executor.config)
    params = config.recommendation
    for key in ("external_count", "internal_count", "triage_per_topic", "internal_triage_limit", "candidate_cache_limit", "internal_review_days"):
        if type(params[key]) is not int or params[key] < 0:
            raise ValueError(f"recommendation.{key} must be a nonnegative integer")
    if any(topic not in TOPICS or type(count) is not int or count < 0 for topic, count in params.topic_targets.items()):
        raise ValueError("topic_targets must use the four supported topics and nonnegative integer targets")
    state = RecommendationState(params.state_path)
    now = datetime.now(timezone.utc)
    date = report_date(config, now)
    if state.delivered_on(date.isoformat(), config.email.timezone):
        logger.info("Today's digest has already been delivered; skipping discovery and SMTP")
        return
    all_corpus = executor.fetch_zotero_corpus()
    corpus = [c for c in executor.filter_corpus(all_corpus) if c.abstract.strip()]
    if not corpus:
        raise RuntimeError("No usable Zotero abstracts; check collection filters and API access")
    # Use all library identities for exclusion, even when a collection is filtered out.
    library_keys = set().union(*(identity_keys(corpus_to_paper(c)) for c in all_corpus))
    fresh = DiscoveryEngine(config, state).discover()
    external = unique_papers(fresh + state.cached_candidates(), library_keys | state.sent_keys())
    external = [p for p in external if title_key(p.title + p.abstract) not in state.data["irrelevant_external"]]
    if external:
        external = executor.reranker.rerank(external, corpus)
    state.cache_candidates(external, params.candidate_cache_limit)
    state.save()  # Discovery progress survives a later model/SMTP failure; no sent flag yet.

    internal = state.internal_candidates(
        unique_papers([corpus_to_paper(c) for c in corpus]), now, params.internal_review_days,
    )
    if internal:
        internal = _rank_internal(internal, corpus, executor.reranker)
    shortlist = _shortlist(external, params.triage_per_topic) + internal[:params.internal_triage_limit]
    accepted = classify_candidates(shortlist, executor.openai_client, config.llm)
    for paper in shortlist:
        if paper.recommendation_reason and (paper.priority == "skip" or paper.primary_topic == "Other"):
            state.data[f"irrelevant_{paper.origin}"].append(title_key(paper.title + paper.abstract))
    for origin in ("internal", "external"):
        state.data[f"irrelevant_{origin}"] = sorted(set(state.data[f"irrelevant_{origin}"]))
    state.save()
    papers = select_daily(
        accepted, dict(params.topic_targets), params.external_count, params.internal_count,
        min(config.executor.max_paper_num, 15),
    )
    logger.info(f"Candidate pools: external={len(external)}, internal={len(internal)}; selected={len(papers)}")
    # Keep the two origins clearly separated in the email, topic order within each.
    papers.sort(key=lambda p: (p.origin == "internal", TOPICS.index(p.primary_topic), -(p.score or 0)))
    for paper in papers:
        hydrate_paper(paper, config)
        paper.generate_analysis(executor.openai_client, config.llm, config.analysis)
        paper.generate_affiliations(executor.openai_client, config.llm)

    if not papers and not config.executor.send_empty:
        logger.info("No eligible recommendations today; no email sent")
        return
    send_email(config, render_email(papers, config, date),
               text=render_email_text(papers, config, date),
               subject=email_subject(len(papers), config, date))
    # Only commit delivery history after SMTP accepts the message.
    state.mark_sent(papers, now, digest_date=date.isoformat())
    logger.info(f"Sent {len(papers)} recommendations; delivery history updated")
