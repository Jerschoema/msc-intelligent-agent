"""Fetch an HTML page and turn it into plain text with honest failure labels.

Status values:
- "ok": text extracted, ready to analyse.
- "captcha": anti-bot challenge (Cloudflare, ScienceDirect, HTTP 403/429).
  We don't try to evade it: record the block, fall back to the abstract.
- "error": network failure.

"""

import ssl
import urllib.error
import urllib.request
from html.parser import HTMLParser

import certifi

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# Markers seen on the common anti-bot interstitials (Cloudflare, PerimeterX,
# Google's rate-limit page, ScienceDirect). Checked case-insensitively against
# the start of the page, where challenge pages put their title/heading.
_CAPTCHA_MARKERS = (
    "captcha",
    "just a moment",
    "unusual traffic",
    "are you a robot",
    "verify you are human",
    "challenge-platform",
    "attention required",
)


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skipping = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag in self._SKIP:
            self._skipping += 1

    def handle_endtag(self, tag) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data) -> None:
        if not self._skipping and data.strip():
            self.parts.append(" ".join(data.split()))


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return "\n".join(parser.parts)


def _looks_like_captcha(html: str) -> bool:
    head = html[:5000].lower()
    return any(marker in head for marker in _CAPTCHA_MARKERS)


def fetch_html(url: str) -> tuple[str, str]:
    """Fetch a page. Returns ``(status, text)`` with status ok|captcha|error.

    Never raises: every outcome maps to a status the caller can report, which
    is what lets the final brief say per source *why* content is missing.
    """
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "research-agent/0.1 (academic research)"}
        )
        with urllib.request.urlopen(request, timeout=30, context=_SSL_CONTEXT) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        # Publishers answer bots with 403/429 challenge pages; that is a block,
        # not a network fault, so label it as one.
        status = "captcha" if exc.code in (403, 429) else "error"
        print(f"[web_fetch] HTTP {exc.code} for {url!r} -> {status}")
        return (status, "")
    except Exception as exc:  # noqa: BLE001
        print(f"[web_fetch] fetch failed for {url!r}: {exc}")
        return ("error", "")

    if _looks_like_captcha(raw):
        return ("captcha", "")
    text = html_to_text(raw)
    if len(text) < 200:
        # A JS-only shell with no server-rendered text: nothing to analyse.
        return ("error", "")
    return ("ok", text)
