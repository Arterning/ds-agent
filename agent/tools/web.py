"""
Web tools — search and fetch.

- web_search: DuckDuckGo Instant Answer API (free, no API key)
- web_fetch:  fetch a URL and extract plain text
"""

import re
import requests
from html.parser import HTMLParser

DUCKDUCKGO_API = "https://api.duckduckgo.com/"
REQUEST_TIMEOUT = 15
MAX_CONTENT_CHARS = 50_000


# ═════════════════════════════════════════════════════════════════════════════
# HTML → text extractor
# ═════════════════════════════════════════════════════════════════════════════

class _TextExtractor(HTMLParser):
    """Extract plain text from HTML, preserving paragraph structure."""

    def __init__(self):
        super().__init__()
        self._text: list[str] = []
        self._skip_tags: set[str] = {"script", "style", "noscript", "head"}
        self._block_tags: set[str] = {
            "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
            "li", "tr", "br", "hr", "section", "article", "pre",
        }
        self._skip_depth: int = 0

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in self._skip_tags:
            self._skip_depth += 1
        if tag_lower in self._block_tags and self._text:
            self._text.append("\n")
        self._current_tag = tag_lower

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag_lower in self._block_tags and self._text:
            self._text.append("\n")

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            self._text.append(text + " ")

    def get_text(self) -> str:
        raw = "".join(self._text)
        raw = re.sub(r" +", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        title = title.replace("&quot;", '"').replace("&#39;", "'")
        return title
    return ""


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    return extractor.get_text()


# ═════════════════════════════════════════════════════════════════════════════
# Public tools (sync — the agent loop is synchronous)
# ═════════════════════════════════════════════════════════════════════════════

def web_search(query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo Instant Answer API.  Returns JSON."""
    if not query or not query.strip():
        return '{"error": "query cannot be empty"}'

    max_results = min(max(max_results, 1), 10)

    print(f"  \033[34m[web] search: {query[:80]}\033[0m")

    try:
        resp = requests.get(
            DUCKDUCKGO_API,
            params={"q": query.strip(), "format": "json", "no_html": 1},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code not in (200, 202):
            return f'{{"error": "search request failed: HTTP {resp.status_code}"}}'

        data = resp.json()
        results: list[dict] = []

        for topic in data.get("RelatedTopics", []):
            if topic.get("Text") and topic.get("FirstURL"):
                results.append({
                    "title": topic["Text"].split(" - ")[0].strip()
                             if " - " in topic.get("Text", "") else topic.get("Text", ""),
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", ""),
                })
            if len(results) >= max_results:
                break

        if len(results) < max_results and data.get("AbstractText"):
            abstract_url = data.get("AbstractURL", "")
            if abstract_url:
                results.append({
                    "title": data.get("Heading", "DuckDuckGo Abstract"),
                    "url": abstract_url,
                    "snippet": data.get("AbstractText", ""),
                })

        if not results:
            return '{"total": 0, "results": [], "hint": "no results, try more specific keywords"}'

        import json
        return json.dumps({
            "total": len(results),
            "query": query,
            "results": results,
        }, ensure_ascii=False)

    except Exception as e:
        print(f"  \033[31m[web] search error: {e}\033[0m")
        return f'{{"error": "{e}"}}'


def web_fetch(url: str) -> str:
    """Fetch a URL, extract plain text, and return it.

    Returns up to {MAX_CONTENT_CHARS} characters of readable text.
    """
    if not url or not url.strip():
        return '{"error": "url cannot be empty"}'

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return f'{{"error": "unsupported protocol: {url[:50]}"}}'

    print(f"  \033[34m[web] fetch: {url[:120]}\033[0m")

    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if resp.status_code != 200:
            return f'{{"error": "fetch failed: HTTP {resp.status_code}"}}'

        html = resp.text
        if resp.encoding and resp.encoding.lower() != "utf-8":
            try:
                html = resp.content.decode(resp.encoding)
            except Exception:
                html = resp.text

        title = _extract_title(html) or url.split("/")[-1] or url
        text = _html_to_text(html)

        if not text or len(text.strip()) < 50:
            return f'{{"error": "content too short or empty (dynamic page?), got {len(text)} chars"}}'

        if len(text) > MAX_CONTENT_CHARS:
            text = text[:MAX_CONTENT_CHARS] + "\n\n...[truncated]"

        import json
        return json.dumps({
            "title": title,
            "url": url,
            "content_length": len(text),
            "content": text,
        }, ensure_ascii=False)

    except Exception as e:
        print(f"  \033[31m[web] fetch error: {e}\033[0m")
        return f'{{"error": "{e}"}}'
