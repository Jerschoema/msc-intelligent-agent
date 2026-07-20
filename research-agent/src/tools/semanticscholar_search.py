"""Search Semantic Scholar (Graph API) and hand back our own Source objects.

Free; API key optional (SEMANTIC_SCHOLAR_API_KEY). Without one, requests share
a throttled public pool, so a 429 is expected here. We treat it for simplicity sake like
an empty result, letting the model switch engines. But unlikely because local LLMs are not
that fast.


"""

import json
import ssl
import urllib.parse
import urllib.request

import certifi

from src.config.settings import settings
from src.models import Source

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "paperId,title,abstract,year,publicationDate,authors,venue,externalIds,openAccessPdf,citationCount"


def _to_source(paper: dict) -> Source:
    """Map one Semantic Scholar paper to a Source. Unit-testable, offline."""
    pdf_url = (paper.get("openAccessPdf") or {}).get("url") or ""
    external = paper.get("externalIds") or {}
    publication_date = paper.get("publicationDate") or (
        f"{paper['year']}-01-01" if paper.get("year") else ""
    )
    return Source(
        id=paper.get("paperId", ""),
        title=" ".join((paper.get("title") or "").split()),
        authors=[a.get("name", "") for a in paper.get("authors", [])],
        abstract=(paper.get("abstract") or "").strip(),
        publication_date=publication_date,
        journal=paper.get("venue") or "",
        source_db="semanticscholar",
        url=f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}",
        full_text_url=pdf_url,
        file_type="pdf",
        doi=str(external.get("DOI") or ""),
        citations=int(paper.get("citationCount") or 0),
        restricted=not pdf_url,
    )


def search_semanticscholar(query: str, max_results: int | None = None) -> list[Source]:
    """Search Semantic Scholar. Returns ``[]`` on error/rate-limit (never raises)."""
    max_results = max_results or settings.search_max_results
    params = urllib.parse.urlencode({"query": query, "limit": max_results, "fields": _FIELDS})
    headers = {"User-Agent": "research-agent/0.1"}
    if settings.semanticscholar_api_key:
        headers["x-api-key"] = settings.semanticscholar_api_key
    try:
        request = urllib.request.Request(f"{_API}?{params}", headers=headers)
        with urllib.request.urlopen(request, timeout=30, context=_SSL_CONTEXT) as resp:
            data = json.load(resp)
        return [_to_source(p) for p in data.get("data", [])]
    except Exception as exc:  # noqa: BLE001
        # Includes HTTP 429 from the shared public pool — expected without a key.
        print(f"[semanticscholar_search] search failed for {query!r}: {exc}")
        return []
