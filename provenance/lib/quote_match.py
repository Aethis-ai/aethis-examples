"""Quote-occurrence and deep-link semantics, mirrored from the engine.

The public API validates a citation at publish time by fetching the cited
document, digesting the exact bytes, and asserting the quoted text occurs in
that document. Exact-text normalization reproduces those semantics. Quoted prefix/suffix
context must also occur around the same actual quote; a constructed fragment
alone is insufficient. This context boundary may reject legacy exact-only
references and is reported as source drift rather than silently repinned. The
repository-side gate withholds references whose supplied selectors cannot
locate their quoted text.

The rules, from the published contract:

* the comparison is **verbatim after whitespace normalisation** - runs of
  whitespace collapse to a single space on both sides;
* ``text/html`` and ``application/xhtml+xml`` sources are additionally
  **tag/script/style-stripped** before comparison (a quote cites prose, not
  markup);
* ``application/pdf`` sources are compared against **extracted page text**,
  and the page the quote is found on drives the ``#page=N`` deep link;
* everything else is compared as decoded text, unstripped;
* **no stemming, no case folding, no fuzzy matching** - the quoted words and
  their order must appear exactly.

Deep links are derived from the target URL plus the quote: a percent-encoded
``#:~:text=`` text fragment for HTML/text, ``#page=N`` for PDF.

``provenance/selftest.py`` locks these semantics against a corpus of cases,
including the ones that distinguish this behaviour from a naive substring
match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote as _pct_quote

# Media types the contract distinguishes. Anything that is neither HTML nor
# PDF is treated as plain text.
MEDIA_HTML = "html"
MEDIA_PDF = "pdf"
MEDIA_TEXT = "text"

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(
    rb"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>|<[^>]+>",
    re.IGNORECASE | re.DOTALL,
)
_PAGE_LOCATOR_RE = re.compile(r"(?:^|\b)(?:page|p\.?)\s*(\d+)", re.IGNORECASE)

# Bounded page walk, matching the engine's cap: a pathological page tree must
# not be able to spin the check.
PDF_MAX_PAGES = 2000


class PDFExtractionError(ValueError):
    """A PDF source could not be parsed into text. Fails the citation closed
    (``reason_code: pdf_extraction_failed``)."""


@dataclass(frozen=True)
class Quote:
    """The verbatim cited text, with optional locating context.

    Mirrors the ``SourceQuote`` wire shape (a W3C Web Annotation
    TextQuoteSelector): ``exact`` is the passage; ``prefix``/``suffix`` are
    optional short verbatim context that disambiguate the deep link.
    """

    exact: str
    prefix: Optional[str] = None
    suffix: Optional[str] = None

    def as_wire(self) -> dict:
        out: dict = {"exact": self.exact}
        if self.prefix:
            out["prefix"] = self.prefix
        if self.suffix:
            out["suffix"] = self.suffix
        return out


def media_type_from_content_type(content_type: str) -> str:
    """Map a ``Content-Type`` header onto the contract's media type."""
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct == "application/pdf":
        return MEDIA_PDF
    if ct in ("text/html", "application/xhtml+xml"):
        return MEDIA_HTML
    return MEDIA_TEXT


def normalise_ws(text: str) -> str:
    """Collapse whitespace runs to a single space; strip the ends."""
    return _WS_RE.sub(" ", text).strip()


def searchable_text(content: bytes, media_type: str) -> str:
    """Decode fetched bytes into the text a quote is checked against."""
    raw = _TAG_RE.sub(b" ", content) if media_type == MEDIA_HTML else content
    return normalise_ws(raw.decode("utf-8", errors="ignore"))


def extract_pdf_page_texts(content: bytes, max_pages: int = PDF_MAX_PAGES) -> List[str]:
    """Whitespace-normalised text, one entry per page.

    Raises ``PDFExtractionError`` on an unparseable document *and* on a
    missing extractor: an absent dependency must never be mistaken for "the
    quote checked out", so it fails closed exactly like a corrupt file.
    """
    import io

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise PDFExtractionError(
            "PDF citation verification needs the 'pypdf' extractor; install it "
            "or cite an HTML/text rendering of the source"
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(content))
        pages = list(reader.pages)[:max_pages]
        return [normalise_ws(page.extract_text() or "") for page in pages]
    except Exception as exc:
        raise PDFExtractionError(f"could not extract PDF text: {exc}") from exc


def _quote_in_text(quote: Quote, text: str) -> bool:
    needle = normalise_ws(quote.exact)
    if not needle:
        return False
    prefix = normalise_ws(quote.prefix or "")
    suffix = normalise_ws(quote.suffix or "")
    start = text.find(needle)
    while start >= 0:
        end = start + len(needle)
        if (not prefix or text[:start].rstrip().endswith(prefix)) and (not suffix or text[end:].lstrip().startswith(suffix)):
            return True
        start = text.find(needle, start + 1)
    return False


def find_pdf_quote_page(content: bytes, quote: Quote) -> Optional[int]:
    """1-based number of the first page containing the quote, else ``None``."""
    needle = normalise_ws(quote.exact)
    if not needle:
        return None
    for page_no, text in enumerate(extract_pdf_page_texts(content), start=1):
        if _quote_in_text(quote, text):
            return page_no
    return None


def quote_occurs(quote: Quote, content: bytes, media_type: str) -> bool:
    """True iff the quote occurs verbatim (whitespace-normalised) in the
    fetched source. An unparseable PDF returns False - fail closed."""
    if media_type == MEDIA_PDF:
        try:
            return find_pdf_quote_page(content, quote) is not None
        except PDFExtractionError:
            return False
    haystack = searchable_text(content, media_type)
    return _quote_in_text(quote, haystack)


def build_deep_link(
    url: str,
    quote: Quote,
    media_type: str,
    locator: Optional[str] = None,
    pdf_page: Optional[int] = None,
) -> str:
    """Self-locating link derived from target plus quote.

    HTML and text get a percent-encoded ``#:~:text=`` fragment: every
    non-unreserved byte is encoded, so a quote containing markup can never
    inject into the emitted link. PDF gets ``#page=N`` from the page the
    quote was found on, falling back to a page-shaped locator, else the bare
    URL.
    """
    base = url.split("#", 1)[0]
    if media_type == MEDIA_PDF:
        if pdf_page is not None:
            return f"{base}#page={pdf_page}"
        if locator:
            match = _PAGE_LOCATOR_RE.search(locator)
            if match:
                return f"{base}#page={match.group(1)}"
        return base
    frag = _pct_quote(normalise_ws(quote.exact), safe="")
    if quote.prefix:
        frag = f"{_pct_quote(normalise_ws(quote.prefix), safe='')}-,{frag}"
    if quote.suffix:
        frag = f"{frag},-{_pct_quote(normalise_ws(quote.suffix), safe='')}"
    return f"{base}#:~:text={frag}"
