from dataclasses import dataclass
from typing import Optional, TypeVar
from datetime import datetime
import re
import tiktoken
from openai import OpenAI
from loguru import logger
import json
from .analysis import (
    ANALYSIS_SYSTEM_PROMPT, DEFAULT_RESEARCH_PROFILE, PaperAnalysis,
    parse_analysis, select_paper_input,
)
RawPaperItem = TypeVar('RawPaperItem')

@dataclass
class Paper:
    source: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: Optional[str] = None
    full_text: Optional[str] = None
    tldr: Optional[str] = None
    affiliations: Optional[list[str]] = None
    score: Optional[float] = None
    analysis: Optional[PaperAnalysis] = None
    origin: str = "external"
    primary_topic: str = "Other"
    published_date: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    zotero_key: Optional[str] = None
    venue: Optional[str] = None
    content_url: Optional[str] = None
    priority: str = "medium"
    recommendation_reason: str = ""

    def generate_analysis(self, openai_client: OpenAI, llm_params: dict,
                          analysis_params: dict | None = None) -> PaperAnalysis:
        """One structured call per paper; failures preserve the original abstract."""
        params = analysis_params if analysis_params is not None else {}
        evidence_source = "abstract"
        try:
            if not (self.abstract or self.full_text):
                raise ValueError("No abstract or extracted body available")
            source, evidence_source = select_paper_input(
                self.title, self.abstract, self.full_text,
                budget=params.get("input_token_budget", 12000),
            )
            profile = params.get("research_profile", DEFAULT_RESEARCH_PROFILE)
            response = openai_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Research profile:\n{profile}\n\nEvidence level: {evidence_source}\nPaper source:\n{source}"},
                ],
                **llm_params.get("generation_kwargs", {}),
            )
            self.analysis = parse_analysis(response.choices[0].message.content, source, evidence_source)
            self.tldr = self.analysis.summary
        except Exception as exc:
            logger.warning(f"Structured analysis failed for {self.url}: {type(exc).__name__}")
            self.tldr = self.abstract or "未提供摘要"
            self.analysis = PaperAnalysis(
                summary=self.tldr, evidence_source=evidence_source, status="failed",
            )
        return self.analysis

    def _generate_tldr_with_llm(self, openai_client:OpenAI,llm_params:dict) -> str:
        lang = llm_params.get('language', 'English')
        prompt = f"Given the following information of a paper, generate a one-sentence TLDR summary in {lang}:\n\n"
        if self.title:
            prompt += f"Title:\n {self.title}\n\n"

        if self.abstract:
            prompt += f"Abstract: {self.abstract}\n\n"

        if self.full_text:
            prompt += f"Preview of main content:\n {self.full_text}\n\n"

        if not self.full_text and not self.abstract:
            logger.warning(f"Neither full text nor abstract is provided for {self.url}")
            return "Failed to generate TLDR. Neither full text nor abstract is provided"
        
        # use gpt-4o tokenizer for estimation
        enc = tiktoken.encoding_for_model("gpt-4o")
        prompt_tokens = enc.encode(prompt)
        prompt_tokens = prompt_tokens[:4000]  # truncate to 4000 tokens
        prompt = enc.decode(prompt_tokens)
        
        response = openai_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": f"You are an assistant who perfectly summarizes scientific paper, and gives the core idea of the paper to the user. Your answer should be in {lang}.",
                },
                {"role": "user", "content": prompt},
            ],
            **llm_params.get('generation_kwargs', {})
        )
        tldr = response.choices[0].message.content
        return tldr
    
    def generate_tldr(self, openai_client:OpenAI,llm_params:dict) -> str:
        try:
            tldr = self._generate_tldr_with_llm(openai_client,llm_params)
            self.tldr = tldr
            return tldr
        except Exception as e:
            logger.warning(f"Failed to generate tldr of {self.url}: {e}")
            tldr = self.abstract
            self.tldr = tldr
            return tldr

    def _generate_affiliations_with_llm(self, openai_client:OpenAI,llm_params:dict) -> Optional[list[str]]:
        if self.full_text is not None:
            prompt = f"Given the beginning of a paper, extract the affiliations of the authors in a python list format, which is sorted by the author order. If there is no affiliation found, return an empty list '[]':\n\n{self.full_text}"
            # use gpt-4o tokenizer for estimation
            enc = tiktoken.encoding_for_model("gpt-4o")
            prompt_tokens = enc.encode(prompt)
            prompt_tokens = prompt_tokens[:2000]  # truncate to 2000 tokens
            prompt = enc.decode(prompt_tokens)
            affiliations = openai_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an assistant who perfectly extracts affiliations of authors from a paper. You should return a python list of affiliations sorted by the author order, like [\"TsingHua University\",\"Peking University\"]. If an affiliation is consisted of multi-level affiliations, like 'Department of Computer Science, TsingHua University', you should return the top-level affiliation 'TsingHua University' only. Do not contain duplicated affiliations. If there is no affiliation found, you should return an empty list [ ]. You should only return the final list of affiliations, and do not return any intermediate results.",
                    },
                    {"role": "user", "content": prompt},
                ],
                **llm_params.get('generation_kwargs', {})
            )
            affiliations = affiliations.choices[0].message.content

            affiliations = re.search(r'\[.*?\]', affiliations, flags=re.DOTALL).group(0)
            affiliations = json.loads(affiliations)
            if not isinstance(affiliations, list) or any(not isinstance(a, str) for a in affiliations):
                raise ValueError("Affiliations must be a list of strings")
            affiliations = list(dict.fromkeys(a.strip() for a in affiliations if a.strip()))

            return affiliations
    
    def generate_affiliations(self, openai_client:OpenAI,llm_params:dict) -> Optional[list[str]]:
        try:
            affiliations = self._generate_affiliations_with_llm(openai_client,llm_params)
            self.affiliations = affiliations
            return affiliations
        except Exception as e:
            logger.warning(f"Failed to generate affiliations of {self.url}: {e}")
            self.affiliations = None
            return None
@dataclass
class CorpusPaper:
    title: str
    abstract: str
    added_date: datetime
    paths: list[str]
    zotero_key: Optional[str] = None
    published_date: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    authors: Optional[list[str]] = None
