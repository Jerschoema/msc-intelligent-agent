"""The ranking agent fills each source's ranking (reputation tier) and the provides the justification.

A static registry (resources/source_registry.json) is maintained by the developers. For instance,
here we can maintain a vetted list of journals, newspaper and other sources that we know to be reliable.


The model is used to classify sources that we have not classified ourselves, and its decisions are cached
so we do not have to repeat this process all the time. 

It processes any source without a ranking on the blackboard.
"""

import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.config.settings import settings
from src.models import Decision

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "resources" / "source_registry.json"


class _RankSchema(BaseModel):
    tier: Literal["high", "medium", "low", "unknown"]
    justification: str = ""  


_SYSTEM = (
    "You classify the reputation of a source for academic research based on the publisher (not the authors)" \
    "Examples of publishers include Nature, IEEE, ACM, New York Times, BBC, arXiv. " \
    "Usage: "
    "1. For every publisher, return its tier:\n"
    "- high: peer-reviewed journals and established quality press "
    "(Examples: Nature, IEEE, BBC, New York Times)\n"
    "- medium: preprint servers, aggregators, respected industry sources "
    "(Examples: arXiv, Wikipedia, ACM Queue)\n"
    "- low: SEO blogs, anonymous or unmoderated sources\n"
    "- unknown: you genuinely cannot judge this publisher\n"
    "2. Be conservative: prefer 'unknown' over guessing. One sentence of "
    "justification.\n\n"
    'Example publisher: "arxiv.org" will have tier: "medium", justification: "Leading '
    'preprint server, but no peer review before posting."'
)


def _domain(url: str) -> str:
    """Registrable-ish domain of a URL: netloc, lower-cased, without www."""
    netloc = urlparse(url).netloc.lower()
    return netloc.removeprefix("www.")


class RankingAgent:
    name = "RankingAgent"

    def __init__(self, blackboard, llm) -> None:
        self.bb = blackboard
        self.llm = llm
        self._cache_path = Path(settings.data_dir) / "registry-cache.json"

    def run(self) -> None:
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        cache = self._load_cache()

        for source in self.bb.sources():
            if source.ranked:
                continue  
            try:
                self._rank(source, registry, cache)
            except Exception as exc:  
                # This prevents a single failure from blocking the whole run.
                self.bb.post(
                    self.name, "decision",
                    Decision(self.name, "error",
                             f"ranking failed for {source.id}: {exc}").to_dict(),
                )

    def _rank(self, source, registry: dict, cache: dict) -> None:
        # if in the search engine the journal is not available we can use the domain source
        publisher = source.journal or _domain(source.url) or "unknown"
        if publisher in registry:
            tier, note, via = registry[publisher]["tier"], registry[publisher]["description"], "registry"
        elif publisher in cache:
            entry = cache[publisher]
            tier, note, via = entry["tier"], entry.get("note") or entry.get("description", ""), "cache"
        else:
            tier, note = self._classify(publisher)
            via = "llm"
            if tier != "unknown":
                # save in the cache
                cache[publisher] = {"tier": tier, "note": note}
                self._save_cache(cache)
        source.ranking = tier
        source.ranking_note = note
        self.bb.save_source(source)
        self.bb.post(
            self.name, "decision",
            Decision(self.name, "ranked", f"{source.id} ({publisher}): {tier} — {note} [{via}]",
                     {"source_id": source.id}).to_dict(),
        )

    def _classify(self, publisher: str) -> tuple[str, str]:
        try:
            parsed = self.llm.with_structured_output(_RankSchema).invoke(
                [SystemMessage(_SYSTEM), HumanMessage(f"Publisher: {publisher}")]
            )
            return parsed.tier, parsed.justification
        except Exception as exc: 
            # Any failure will not stop the entire run.
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error",
                         f"ranking failed for {publisher!r}: {exc}").to_dict(),
            )
            return "unknown", ""

    def _load_cache(self) -> dict:
        if self._cache_path.exists():
            return json.loads(self._cache_path.read_text(encoding="utf-8"))
        return {}

    def _save_cache(self, cache: dict) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
