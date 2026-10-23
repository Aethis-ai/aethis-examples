"""Bounded fetch + digest of a cited source, mirrored from the engine.

Every bound the publish path enforces is enforced here: total timeout, a
response-size cap, a redirect cap with each hop re-validated from scratch, and
a hard requirement that the final response be a 200. Nothing blocks on stdin
and every network call carries an explicit timeout, so this is safe to run
unattended in CI.

The digest is taken over the **exact bytes fetched**, which is what binds a
citation to a version of its document: if the authority republishes, the
digest moves and the citation fails closed until a human re-reads the passage
and re-pins it. That is the intended behaviour, not a flake.
"""

from __future__ import annotations

import hashlib
import http.client
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin

from .quote_match import media_type_from_content_type
from .target_safety import Resolver, TargetSafetyError, resolve_and_vet, validate_target_url

# Deliberately conservative bounds: cited sources are legislation, guidance
# and specification documents, not media.
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3

USER_AGENT = "aethis-examples-provenance-check/1.0"


@dataclass
class FetchedSource:
    """The bytes a citation was verified against, plus how they were obtained."""

    url: str
    content: bytes
    media_type: str
    hops: List[str] = field(default_factory=list)

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.content).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Suppress transparent redirect following so every hop is re-validated."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _content_length(value: Optional[str], max_bytes: int) -> Optional[int]:
    if value is None:
        return None
    digits = value.strip(" \t")
    if not digits or any(char < "0" or char > "9" for char in digits):
        raise TargetSafetyError("incomplete_response", "Source Content-Length must be ASCII decimal")
    # Strip leading zeros before bounded comparison/conversion. No untrusted
    # numeral can reach int() while larger than the supported response cap.
    canonical = digits.lstrip("0") or "0"
    cap = str(max_bytes)
    if len(canonical) > len(cap) or (len(canonical) == len(cap) and canonical > cap):
        raise TargetSafetyError("oversize_response", f"Source declares more than the {max_bytes}-byte cap")
    return int(canonical)


def read_complete_response(
    response: http.client.HTTPResponse | urllib.error.HTTPError,
    *, max_bytes: int = MAX_RESPONSE_BYTES,
) -> bytes:
    """Read once within the cap and verify the normalized HTTP declaration.

    HTTPResponse may silently discard a large zero-padded Content-Length.
    Validate the original header independently of its internal integer parser.
    Reader programming exceptions remain visible to the caller.
    """
    declared = _content_length(response.headers.get("content-length"), max_bytes)
    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise TargetSafetyError("oversize_response", f"Response exceeded the {max_bytes}-byte cap")
    if declared is not None and len(body) != declared:
        raise TargetSafetyError("incomplete_response", "Response body does not match Content-Length")
    remaining = getattr(response, "length", None)
    if isinstance(remaining, int) and remaining > 0:
        raise TargetSafetyError("incomplete_response", "Response reader retains unread declared bytes")
    return body


def fetch_source(
    url: str,
    *,
    resolver: Optional[Resolver] = None,
    opener=None,
    max_bytes: int = MAX_RESPONSE_BYTES,
    timeout_seconds: float = FETCH_TIMEOUT_SECONDS,
    max_redirects: int = MAX_REDIRECTS,
) -> FetchedSource:
    """Validate and fetch ``url`` with every bound enforced.

    Each redirect hop is re-validated from scratch (scheme, credentials, host
    class, DNS). Raises ``TargetSafetyError`` on any violation.
    """
    build = opener or urllib.request.build_opener(_NoRedirect)
    hops: List[str] = []
    current = url

    for _hop in range(max_redirects + 1):
        normalised, ascii_host = validate_target_url(current)
        resolve_and_vet(ascii_host, resolver)
        hops.append(normalised)

        request = urllib.request.Request(normalised, headers={"User-Agent": USER_AGENT})
        try:
            response = build.open(request, timeout=timeout_seconds)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("location")
                if not location:
                    raise TargetSafetyError(
                        "fetch_failure", f"Redirect from {normalised!r} without a Location header"
                    )
                current = urljoin(normalised, location)
                exc.close()
                continue
            raise TargetSafetyError("fetch_failure", f"{normalised!r} returned HTTP {exc.code}")
        except urllib.error.URLError as exc:
            raise TargetSafetyError("fetch_failure", f"Fetch failed for {normalised!r}: {exc.reason}")
        except TimeoutError:
            raise TargetSafetyError("fetch_timeout", f"Timed out fetching {normalised!r}")

        try:
            with response:
                if response.status != 200:
                    raise TargetSafetyError("fetch_failure", f"{normalised!r} returned HTTP {response.status}")
                body = read_complete_response(response, max_bytes=max_bytes)
                return FetchedSource(
                    url=normalised,
                    content=body,
                    media_type=media_type_from_content_type(response.headers.get("content-type", "")),
                    hops=hops,
                )
        except (OSError, http.client.HTTPException) as exc:
            reason = "fetch_timeout" if isinstance(exc, TimeoutError) else "fetch_failure"
            raise TargetSafetyError(reason, f"{type(exc).__name__}: source response read failed") from exc

    raise TargetSafetyError("too_many_redirects", f"{url!r} exceeded the {max_redirects}-redirect bound")
