"""Search arXiv and hand back our own Source objects.

Free, no API key, PDFs are text-based so we skip OCR entirely. Great for
the scope of the assignment because does not require advanced setup for
instructor or rate limits that prevent me from experimenting with the code.
"""

import arxiv

from src.config.settings import settings
from src.models import Source


def _to_source(result) -> Source:
    """Map one arXiv result to a Source. Kept separate so it's unit-testable."""
    short_id = result.get_short_id()
    return Source(
        id=short_id,
        title=" ".join(result.title.split()),
        authors=[a.name for a in result.authors],
        abstract=" ".join(result.summary.split()),
        publication_date=result.published.date().isoformat() if result.published else "",
        journal="arxiv.org",
        source_db="arxiv",
        url=result.entry_id or "",
        full_text_url=result.pdf_url or "",
        file_type="pdf",
        document_type="preprint",
        language="en",  # arXiv accepts English submissions only
        # arXiv is open access by construction, so restricted stays False.
    )


def search_arxiv(query: str, max_results: int | None = None) -> list[Source]:
    """Search arXiv. Returns ``[]`` on no results or any error (never raises)."""
    max_results = max_results or settings.search_max_results
    try:
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        client = arxiv.Client()
        return [_to_source(r) for r in client.results(search)]
    except Exception as exc:  # noqa: BLE001
        # Network issues should not grind the whole process to a halt.
        print(f"[arxiv_search] search failed for {query!r}: {exc}")
        return []
