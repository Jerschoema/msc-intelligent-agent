"""Search OpenAlex and hand back our own Source objects.

OpenAlex (https://openalex.org) indexes ~250M scholarly works across every
field, no API key needed.

Results per query come from SEARCH_MAX_RESULTS.


"""

import json
import ssl
import urllib.parse
import urllib.request

import certifi

from src.config.settings import settings
from src.models import Source

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
_API = "https://api.openalex.org/works"


def _reconstruct_abstract(inverted: dict | None) -> str:
    """Rebuild "the cat sat" from {"the": [0], "cat": [1], "sat": [2]}."""
    if not inverted:
        return ""
    positions = [(pos, word) for word, poss in inverted.items() for pos in poss]
    return " ".join(word for _, word in sorted(positions))


def _to_source(work: dict) -> Source:
    """Map one OpenAlex work to a Source. Kept separate so it's unit-testable."""
    work_id = (work.get("id") or "").rsplit("/", 1)[-1] 
    oa_location = work.get("best_oa_location") or {}
    primary = work.get("primary_location") or {}
    pdf_url = oa_location.get("pdf_url") or ""
    # No PDF but an open landing page -> an HTML source we can still fetch.
    full_text_url = pdf_url or (oa_location.get("landing_page_url") or "")
    # The citation link (and the ranker's domain fallback) needs the actual
    # publisher's page, not OpenAlex's own work ID — only fall back to the
    # ID when no publisher page is known at all.
    landing_page = primary.get("landing_page_url") or oa_location.get("landing_page_url") or work.get("id") or ""
    return Source(
        id=work_id,
        title=" ".join((work.get("title") or "").split()),
        authors=[(a.get("author") or {}).get("display_name", "") for a in work.get("authorships", [])],
        abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
        publication_date=work.get("publication_date") or "",
        journal=(primary.get("source") or {}).get("display_name") or "",
        source_db="openalex",
        url=landing_page,
        full_text_url=full_text_url,
        file_type="pdf" if pdf_url else "html",
        doi=(work.get("doi") or "").removeprefix("https://doi.org/"),
        citations=int(work.get("cited_by_count") or 0),
        document_type=work.get("type") or "",  # e.g. "article", "preprint"
        language=work.get("language") or "",
        # Restricted = no retrievable full text — the abstract collected
        # above is all this source has to go on.
        restricted=not full_text_url,
    )


def search_openalex(query: str, max_results: int | None = None) -> list[Source]:
    """Search OpenAlex. Returns ``[]`` on no results or any error (never raises)."""
    max_results = max_results or settings.search_max_results
    params = urllib.parse.urlencode({
        "search": query,
        "per-page": max_results,
        "mailto": "research-agent@example.org",  # OpenAlex "polite pool"
    })
    try:
        request = urllib.request.Request(
            f"{_API}?{params}", headers={"User-Agent": "research-agent/0.1"}
        )
        with urllib.request.urlopen(request, timeout=30, context=_SSL_CONTEXT) as resp:
            data = json.load(resp)
        return [_to_source(w) for w in data.get("results", [])]
    except Exception as exc:  # noqa: BLE001
        print(f"[openalex_search] search failed for {query!r}: {exc}")
        return []
