""" Here are the data models for the research agent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


@dataclass
class Claim:
    """One claim from a source, with evidence and its page so a researcher can verify the claim."""

    text: str
    evidence: str = ""
    page: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        return cls(text=d.get("text", ""), evidence=d.get("evidence", ""), page=d.get("page", 0))


@dataclass
class Source:
    """This is the model for a single source of information enriched by various agents.

    
    - the researcher agent creates the source from a search result and records how
      it was found (topic, query) and whether the source was fully accessible
        (restricted means that only an abstract or summary is available without a subscription),
      captcha means that they use cloudfare or other defenses that prevent our program from accessing the source.
    
    - the parser agent fills content and pages (the full text with [page N] markers);
    - the summary agent fills summary and claims;
    - the ranker fills ranking and ranking_note;
    - the summary agent also fills relevance and relevance_note: whether the
      source is actually about the topic, not just adjacent to it;
    - the index step is flag that once is true means that the chunks are in the vector store;
    - the discovery agent fills discovery with terms for further queries.
    - then there are generic, self-explaining metadata about a source, like title, authors, abstract, publication date, journal, source database, url, full text url, file type, doi, citations, document type and language.
    """

    id: str
    # -- discovery metadata, from the search engines --
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    publication_date: str = ""  # ISO date
    journal: str = ""  # journal or site name
    source_db: str = ""  # arxiv | openalex | semanticscholar
    url: str = ""  # landing page — the citation link
    full_text_url: str = ""  # where the document itself lives
    file_type: str = "pdf"  # pdf | html
    doi: str = ""
    citations: int = 0  # times cited (0 = none reported)
    document_type: str = ""  # preprint | article | ...
    language: str = ""  # ISO code, "" = unknown
    topic: str = ""  # what the user asked about
    query: str = ""  # the search query that found it
    # -- access outcomes, from fetching --
    restricted: bool = False  # paywalled: only the abstract is available
    captcha: bool = False  # bot-blocked: we found it but could not collect it
    file_path: str = ""  # the downloaded file on disk
    # -- enrichment, one agent per field --
    content: str = ""  # full text with [page N] markers
    pages: int = 0  # page count
    summary: str = ""
    claims: list[Claim] = field(default_factory=list)
    ranking: str = ""  # high | medium | low | unknown
    ranking_note: str = ""  # why the ranker thinks so
    relevance: str = ""  # relevant | unrelated | "" not judged yet
    relevance_note: str = ""  # why the summariser thinks so
    indexed: bool = False  # chunks are in the vector store
    discovery: dict = field(default_factory=dict)  # {"keywords": [...], "topics": [...]}

    # -- to-do markers: empty field = not done yet --
    @property
    def parsed(self) -> bool:
        return bool(self.content)

    @property
    def summarised(self) -> bool:
        return bool(self.summary)

    @property
    def ranked(self) -> bool:
        return bool(self.ranking)

    @property
    def mined(self) -> bool:
        return bool(self.discovery)

    def describe(self) -> str:
        """One listing line, written for the LLM: the id to act on, title and
        year to judge relevance, a warning when fetching would be wasted."""
        access = " [restricted — abstract only]" if self.restricted else ""
        cited = f", cited {self.citations}×" if self.citations else ""
        return (
            f"- id={self.id} | {self.title} ({self.publication_date[:4]}{cited}){access}\n"
            f"  {self.abstract[:300]}"
        )

    def cite(self) -> str:
        """Academic in-text citation key: 'Shi, 2022', 'Shi & Li, 2022', or
        'Ebert et al., 2018'. Used in the report body so every summary and
        claim names its source the way a paper would."""
        year = self.publication_date[:4] or "n.d."
        surnames = [name.split()[-1] for name in self.authors if name.strip()]
        if not surnames:
            who = self.journal or self.source_db or "unknown"
        elif len(surnames) == 1:
            who = surnames[0]
        elif len(surnames) == 2:
            who = f"{surnames[0]} & {surnames[1]}"
        else:
            who = f"{surnames[0]} et al."
        return f"{who}, {year}"

    def citation_meta(self) -> dict:
        """This source as flat chunk metadata for the vector store.

        Chroma stores scalars only, so the author list is joined and the year
        extracted. Everything needed to cite a retrieved passage — and weigh
        its reliability — travels with the text.
        """
        return {
            "doi": self.doi,
            "title": self.title,
            "authors": "; ".join(self.authors),
            "journal": self.journal,
            "year": int(self.publication_date[:4] or 0),
            "citations": self.citations,
            "reputation": self.ranking or "unknown",
            "document_type": self.document_type,
            "language": self.language,
            "topic": self.topic,
            "query": self.query,
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        # Tolerate extra/missing keys so records written by an older version
        # of the code still load.
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in d.items() if k in known}
        data["claims"] = [Claim.from_dict(c) for c in d.get("claims", [])]
        return cls(**data)


@dataclass(frozen=True)
class Chunk:
    """A slice of a parsed document. ``page`` enables in-text page citations."""

    id: str
    source_id: str
    text: str
    page: int
    chunk_index: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(**d)


@dataclass
class Decision:
    """An audit record for the posts trail. ``kind`` says what happened
    ``reason`` carries the justification meaning the model's own explanation of itself.

    This is also how the system fails gracefully. The system continues and all decisions, error 
    and all other relevant events are appended as a trail to the report.
    """

    made_by: str
    kind: str
    reason: str
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return cls(**d)


@dataclass
class Report:
    """Pointer to the published report. The content lives on disk (Markdown
    and PDF under data/reports/) — the blackboard stores pointers, never
    documents."""

    run_id: str
    path: str  # the canonical Markdown file
    pdf_path: str = ""  # "" when PDF rendering failed (the markdown still stands)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Report":
        return cls(run_id=d["run_id"], path=d["path"], pdf_path=d.get("pdf_path", ""))
