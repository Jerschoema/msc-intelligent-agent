"""The summary agent makes summaries and extracts claims from the sources in the bloackboard.

All sources on the blackboard that have no summary we let the agent write a summary 
and extract up to 4 claims with the supporting evidence. Because an entire document
does not fit in the context window of a small local model, we batch the text into chunks
and summarise each chunk, then merge the summaries into one.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.models import Claim, Decision, Source
from src.tools.pdf_parser import pages_to_text, text_to_pages


class _ClaimSchema(BaseModel):
    text: str
    evidence: str = ""
    page: int = 0


class _SummarySchema(BaseModel):
    summary: str
    claims: list[_ClaimSchema] = []
    justification: str = ""  # the model explains its reading


class _RelevanceSchema(BaseModel):
    relevant: bool
    reason: str = ""


_RELEVANCE_SYSTEM = (
    "You judge whether an academic source is actually about the given research "
    "topic, not merely adjacent to it because it reuses the same technique or "
    "keyword. Read only the title and abstract.\n"
    "relevant=true only if the source's own subject matter addresses the topic "
    "(or the research question) directly. A paper from a different field that "
    "happens to apply the same method is NOT relevant just because of that "
    "overlap. One sentence reason.\n\n"
    'Example: topic "transformer architectures for code generation", title '
    '"An Image is Worth 16x16 Words: Transformers for Image Recognition at '
    'Scale" -> relevant: false, reason: "This applies transformers to image '
    'classification, not code generation."'
)


_SYSTEM = (
    "You summarise an academic source for a research brief. Rules:"
    "1. Use ONLY the text provided. Do not hallucinate or invent anything.\n"
    "2. Write a summary of the content (roughly 200-500 words, longer for "
    "content-rich papers) and extract up to 4 key claims;"
    "3. for each claim quote the supporting passage verbatim and give the page "
    "number from its [page N] marker. Add one sentence of justification "
    "explaining what you based the summary on.\n\n"
    'Example claim: {"text": "The method beats the baseline by 12%", '
    '"evidence": "our statistical analysis of 500 annual reports shows that the method improves accuracy by 12.3% over the baseline", "page": 5}'
)

# A context size that is safe for a small local model.
_CONTENT_BUDGET = 12000


class SummariseAgent:
    name = "SummariseAgent"

    def __init__(self, blackboard, llm) -> None:
        self.bb = blackboard
        self.llm = llm

    def run(self, topic: str = "", research_question: str = "") -> None:
        for source in self.bb.sources():
            if source.summarised:
                continue  
            if not source.content and not source.abstract.strip():
                continue  
            self._check_relevance(source, topic, research_question)
            self._summarise(source)

    def _check_relevance(self, source: Source, topic: str, research_question: str) -> None:
        """Flag sources that only share a technique or keyword with the topic
        but are actually about something else."""
        if not topic.strip():
            return  # nothing to judge against
        try:
            parsed = self.llm.with_structured_output(_RelevanceSchema).invoke([
                SystemMessage(_RELEVANCE_SYSTEM),
                HumanMessage(
                    f"Topic: {topic}\nResearch question: {research_question or topic}\n\n"
                    f"Title: {source.title}\nAbstract: {source.abstract[:800]}"
                ),
            ])
            source.relevance = "relevant" if parsed.relevant else "unrelated"
            source.relevance_note = parsed.reason
            if source.relevance == "unrelated":
                self.bb.post(
                    self.name, "decision",
                    Decision(self.name, "off-topic",
                             f"{source.id} judged off-topic: {parsed.reason}",
                             {"source_id": source.id}).to_dict(),
                )
        except Exception as exc:  # noqa: BLE001
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error",
                         f"relevance check failed for {source.id}: {exc}",
                         {"source_id": source.id}).to_dict(),
            )

    def _batches(self, content: str) -> list[str]:
        """Split content into batches to avoid context window overflow"""
        pages = text_to_pages(content)
        batches: list[str] = []
        current: list[tuple[int, str]] = []
        size = 0
        for page in pages:
            page_text = pages_to_text([page])
            if current and size + len(page_text) > _CONTENT_BUDGET:
                batches.append(pages_to_text(current))
                current, size = [], 0
            current.append(page)
            size += len(page_text)
        if current:
            batches.append(pages_to_text(current))
        return batches or [content[:_CONTENT_BUDGET]]

    def _summarise(self, source: Source) -> None:
        if source.content:
            batches = self._batches(source.content)
            note = "Text of the paper (with [page N] markers):"
        else:
            batches = [source.abstract]
            note = "Only the ABSTRACT is available (no full text). Use page 0 for every claim."

        if len(batches) == 1:
            self._summarise_one_batch(source, note, batches[0])
            return

        # Long paper: summarise each batch (map), then merge into one summary
        partials = [self._extract(source, note, batch) for batch in batches]
        partials = [p for p in partials if p is not None]
        if not partials:
            source.summary = "Summary unavailable."
            self.bb.save_source(source)
            return

        summaries = [summary for summary, _ in partials]
        claims = [c for _, batch_claims in partials for c in batch_claims][:4]
        source.summary = summaries[0] if len(summaries) == 1 else self._integrate(source, summaries)
        source.claims = claims
        self.bb.save_source(source)
        self.bb.post(
            self.name, "decision",
            Decision(self.name, "summarised",
                     f"summarised {source.id} from {len(batches)} batches",
                     {"source_id": source.id}).to_dict(),
        )

    def _summarise_one_batch(self, source: Source, note: str, material: str) -> None:
        structured = self.llm.with_structured_output(_SummarySchema, include_raw=True)
        result = structured.invoke([
            SystemMessage(_SYSTEM),
            HumanMessage(f"Title: {source.title}\n\n{note}\n{material}"),
        ])
        parsed = result.get("parsed")
        if parsed is None:
          
            raw = (getattr(result.get("raw"), "content", "") or "").strip()
            source.summary = raw[:1500] if raw else "Summary unavailable."
            self.bb.save_source(source)
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error",
                         f"structured summary failed for {source.id}: {result.get('parsing_error')}",
                         {"source_id": source.id}).to_dict(),
            )
            return
        source.summary = parsed.summary
        # Abstracts have no pages; zero them so no fake citations appear.
        source.claims = [
            Claim(text=c.text, evidence=c.evidence, page=c.page if source.content else 0)
            for c in parsed.claims
        ]
        self.bb.save_source(source)
        self.bb.post(
            self.name, "decision",
            Decision(self.name, "summarised",
                     parsed.justification or f"summarised {source.id}",
                     {"source_id": source.id}).to_dict(),
        )

    def _extract(self, source: Source, note: str, material: str):
        """One structured extraction call over one batch. None if it didn't parse."""
        structured = self.llm.with_structured_output(_SummarySchema, include_raw=True)
        result = structured.invoke([
            SystemMessage(_SYSTEM),
            HumanMessage(f"Title: {source.title}\n\n{note}\n{material}"),
        ])
        parsed = result.get("parsed")
        if parsed is None:
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error",
                         f"structured summary failed for {source.id}: {result.get('parsing_error')}",
                         {"source_id": source.id}).to_dict(),
            )
            return None
        claims = [Claim(text=c.text, evidence=c.evidence, page=c.page) for c in parsed.claims]
        return parsed.summary, claims

    def _integrate(self, source: Source, summaries: list[str]) -> str:
        """Merge per-batch summaries of one long paper into a single summary."""
        numbered = "\n\n".join(f"Part {i + 1}:\n{s}" for i, s in enumerate(summaries))
        structured = self.llm.with_structured_output(_SummarySchema, include_raw=True)
        result = structured.invoke([
            SystemMessage(_SYSTEM),
            HumanMessage(
                f"Title: {source.title}\n\nBelow are summaries of separate parts "
                f"of the same paper, in order. Write ONE summary of the whole "
                f"paper, roughly 200-500 words.\n\n{numbered}"
            ),
        ])
        parsed = result.get("parsed")
        return parsed.summary if parsed else " ".join(summaries)[:1500]
