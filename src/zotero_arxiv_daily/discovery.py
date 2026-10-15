"""Bounded historical discovery; fetch metadata now and full text only if selected."""

from datetime import datetime, timezone
import os
import re
from time import sleep

import arxiv
from loguru import logger
import requests

from .analysis import safe_url
from .protocol import Paper
from .recommendation import normalize_arxiv, normalize_doi

QUERIES = {
    "VLN": '"vision language navigation" OR "vision-and-language navigation" OR "language guided navigation"',
    "Semantic Mapping": '"semantic mapping" OR "open vocabulary mapping" OR "3D scene graph"',
    "3D Reconstruction": '"3D reconstruction" OR "gaussian splatting" OR "neural reconstruction"',
    "SLAM": '"simultaneous localization and mapping" OR "visual SLAM" OR "lidar SLAM"',
}


def _get(url, *, params=None, headers=None):
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=(10, 40))
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                sleep(3 * (attempt + 1))
                continue
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 2:
                raise
            sleep(3 * (attempt + 1))


def _abstract(index) -> str:
    if not isinstance(index, dict):
        return ""
    words = {}
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and 0 <= position < 20000:
                words[position] = word
    return " ".join(words[p] for p in sorted(words))


def openalex_paper(item: dict, topic: str) -> Paper | None:
    if item.get("is_retracted") or not item.get("open_access", {}).get("is_oa"):
        return None
    if item.get("type") not in {"article", "journal-article", "preprint", "review", "proceedings-article", "conference-paper"}:
        return None
    location = item.get("best_oa_location") or {}
    locations = [location] + [loc for loc in item.get("locations", []) if loc and loc.get("is_oa")]
    pdf = next((safe_url(loc.get("pdf_url")) for loc in locations if safe_url(loc.get("pdf_url"))), None)
    landing = next((safe_url(loc.get("landing_page_url")) for loc in locations
                    if safe_url(loc.get("landing_page_url"))), None)
    abstract = _abstract(item.get("abstract_inverted_index"))
    title = item.get("display_name") or item.get("title")
    if not title or not abstract:
        return None
    source = (item.get("primary_location") or {}).get("source") or {}
    return Paper(
        source="openalex", title=title, abstract=abstract,
        authors=[a["author"].get("display_name", "") for a in item.get("authorships", []) if a.get("author")],
        url=safe_url(item.get("doi")) or landing or item["id"], pdf_url=pdf,
        content_url=landing, doi=normalize_doi(item.get("doi")),
        arxiv_id=normalize_arxiv(landing) or normalize_arxiv(pdf),
        published_date=item.get("publication_date"), venue=source.get("display_name"), primary_topic=topic,
    )


class DiscoveryEngine:
    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.params = config.get("recommendation", {})
        self._raw_counts = {}
        limit = self.params.get("candidates_per_topic_source", 30)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("candidates_per_topic_source must be an integer from 1 to 200")
        if any(source not in {"arxiv", "openalex"} for source in self.params.get("external_sources", [])):
            raise ValueError("external_sources only supports arxiv and openalex")

    def discover(self) -> list[Paper]:
        result = []
        limit = self.params.get("candidates_per_topic_source", 30)
        sources = self.params.get("external_sources", ["arxiv", "openalex"])
        for source in sources:
            for topic, query in QUERIES.items():
                key = f"{source}:{topic}"
                offset = self.state.data["offsets"].get(key, 0)
                if offset >= 9000:
                    offset = 0
                try:
                    papers = self._arxiv(topic, query, offset, limit) if source == "arxiv" else self._openalex(topic, query, offset, limit)
                    result.extend(papers)
                    # Walk search results across days without imposing a publication cutoff.
                    self.state.data["offsets"][key] = offset + limit if self._raw_counts.get(key, len(papers)) else 0
                except Exception as exc:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    hint = "; check OPENALEX_API_KEY/access" if source == "openalex" and status in {401, 403} else ""
                    logger.warning(f"Discovery source {source}, topic {topic} unavailable ({type(exc).__name__}, status={status}{hint}); using remaining sources/cache")
        return result

    def _arxiv(self, topic, query, offset, limit):
        terms = " OR ".join(f'all:"{term}"' for term in re.findall(r'"([^"]+)"', query))
        categories = self.config.source.arxiv.category
        if categories:
            cats = " OR ".join(f"cat:{category}" for category in categories)
            terms = f"({cats}) AND ({terms})"
        # arxiv.py treats max_results as the total bound before subtracting offset.
        search = arxiv.Search(query=terms, max_results=offset + limit, sort_by=arxiv.SortCriterion.Relevance)
        results = arxiv.Client(num_retries=2, delay_seconds=3).results(search, offset=offset)
        papers = []
        for item in results:
            papers.append(Paper(
                source="arxiv", title=item.title, authors=[a.name for a in item.authors],
                abstract=item.summary, url=item.entry_id, pdf_url=item.pdf_url,
                arxiv_id=normalize_arxiv(item.entry_id), doi=normalize_doi(item.doi),
                published_date=item.published.date().isoformat(), primary_topic=topic,
            ))
        return papers

    def _openalex(self, topic, query, offset, limit):
        # OpenAlex pages are bounded; after a complete sweep start a fresh one.
        if offset >= 9000:
            offset = 0
        params = {"search": query, "filter": "open_access.is_oa:true,is_retracted:false",
                  "per-page": limit, "page": offset // limit + 1}
        api_key = self.config.source.get("openalex", {}).get("api_key") or os.environ.get("OPENALEX_API_KEY")
        if api_key:
            params["api_key"] = api_key
        payload = _get("https://api.openalex.org/works", params=params).json()
        self._raw_counts[f"openalex:{topic}"] = len(payload.get("results", []))
        return [paper for item in payload.get("results", []) if (paper := openalex_paper(item, topic))]


def hydrate_paper(paper: Paper, config):
    """Try indexed internal text, then explicit OA/arXiv text. No access bypass."""
    from .retriever.arxiv_retriever import (
        _extract_text_from_tar_worker, _extract_text_from_html_worker,
        _extract_text_from_pdf_worker, _run_with_hard_timeout,
    )
    if paper.origin == "internal" and paper.zotero_key:
        base = f"https://api.zotero.org/users/{config.zotero.user_id}/items"
        headers = {"Zotero-API-Key": str(config.zotero.api_key), "Zotero-API-Version": "3"}
        try:
            children = _get(f"{base}/{paper.zotero_key}/children", headers=headers,
                            params={"itemType": "attachment", "limit": 100}).json()
            for child in children:
                if child.get("data", {}).get("contentType") != "application/pdf":
                    continue
                response = requests.get(f"{base}/{child['key']}/fulltext", headers=headers, timeout=(10, 30))
                if response.status_code == 200 and response.json().get("content"):
                    paper.full_text = response.json()["content"]
                    return
        except Exception as exc:
            logger.debug(f"Zotero indexed text unavailable: {type(exc).__name__}")
    attempts = []
    arxiv_id = paper.arxiv_id or normalize_arxiv(paper.url)
    if arxiv_id:
        attempts.extend([
            (_extract_text_from_tar_worker, (f"https://arxiv.org/e-print/{arxiv_id}", arxiv_id, paper.title)),
            (_extract_text_from_html_worker, (f"https://arxiv.org/html/{arxiv_id}",)),
        ])
        if not paper.pdf_url:
            paper.pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    elif safe_url(paper.content_url):
        attempts.append((_extract_text_from_html_worker, (paper.content_url,)))
    if safe_url(paper.pdf_url):
        attempts.append((_extract_text_from_pdf_worker, (paper.pdf_url,)))
    for func, args in attempts:
        text = _run_with_hard_timeout(func, args, timeout=120,
                                      operation="Selected-paper text extraction", paper_title=paper.title)
        if text and len(text.strip()) > 200:
            if func is _extract_text_from_html_worker:
                # Landing/abstract pages are not evidence of having read the body.
                if len(text) < max(1200, len(paper.abstract) * 2) or not re.search(
                    r"method|experiment|evaluation|discussion|conclusion|theorem", text, re.I
                ):
                    continue
            paper.full_text = text
            return
