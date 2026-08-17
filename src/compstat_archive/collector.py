from __future__ import annotations

import http.cookiejar
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

from .config import BASE_URL, COMPSTAT_PAGE, USER_AGENT, YEAR_END_PAGE
from .models import SourceCandidate


class DownloadError(RuntimeError):
    """Raised when both HTTP and browser download paths fail."""


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def parse_weekly_dates(title: str) -> tuple[date, date] | None:
    match = re.search(
        r"([A-Za-z]+)\s+(\d{1,2})\s+through\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",
        title,
        re.IGNORECASE,
    )
    if not match:
        return None
    start_month, start_day, end_month, end_day, end_year = match.groups()
    end = datetime.strptime(f"{end_month} {end_day} {end_year}", "%B %d %Y").date()
    start = datetime.strptime(f"{start_month} {start_day} {end_year}", "%B %d %Y").date()
    if start > end:
        start = start.replace(year=start.year - 1)
    return start, end


def classify_link(href: str, text: str, discovery_page: str) -> SourceCandidate | None:
    if "showpublisheddocument" not in href.lower():
        return None
    url = urljoin(BASE_URL, href)
    normalized = " ".join(text.split())
    lower = normalized.lower()

    if discovery_page == COMPSTAT_PAGE and "wpd compstat report" in lower:
        dates = parse_weekly_dates(normalized)
        if not dates:
            return None
        return SourceCandidate(
            title=normalized,
            url=url,
            report_type="weekly_compstat",
            report_start=dates[0],
            report_end=dates[1],
            report_year=dates[1].year,
            discovery_page=discovery_page,
        )

    year_match = re.search(r"\b(20\d{2})\b", normalized)
    if discovery_page == COMPSTAT_PAGE and "calendar year-end compstat" in lower:
        if not year_match:
            return None
        year = int(year_match.group(1))
        return SourceCandidate(
            title=normalized,
            url=url,
            report_type="year_end_compstat",
            report_start=date(year, 1, 1),
            report_end=date(year, 12, 31),
            report_year=year,
            discovery_page=discovery_page,
        )

    if discovery_page == YEAR_END_PAGE and "year-end report" in lower:
        if not year_match:
            return None
        year = int(year_match.group(1))
        return SourceCandidate(
            title=normalized,
            url=url,
            report_type="wpd_year_end_report",
            report_start=date(year, 1, 1),
            report_end=date(year, 12, 31),
            report_year=year,
            discovery_page=discovery_page,
        )
    return None


def discover_from_html(html: str, page_url: str) -> list[SourceCandidate]:
    parser = _LinkParser()
    parser.feed(html)
    candidates = []
    seen = set()
    for href, text in parser.links:
        candidate = classify_link(href, text, page_url)
        if candidate and (candidate.report_type, candidate.url) not in seen:
            candidates.append(candidate)
            seen.add((candidate.report_type, candidate.url))
    return candidates


class CityClient:
    """Polite City-site client with a Chromium fallback for CDN blocks."""

    def __init__(self, timeout: float = 45.0, retries: int = 3) -> None:
        self.timeout = timeout
        self.retries = retries
        cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPRedirectHandler(),
        )
        self._browser = None
        self._browser_context = None
        self._playwright = None

    @staticmethod
    def _headers(referer: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/pdf,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
            "Cache-Control": "no-cache",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _http_get(self, url: str, referer: str | None = None) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            request = urllib.request.Request(url, headers=self._headers(referer))
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return response.read()
            except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
                last_error = error
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise DownloadError(f"HTTP fetch failed for {url}: {last_error}")

    def _ensure_browser(self) -> None:
        if self._browser_context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise DownloadError(
                "Browser fallback is unavailable; install the project and Chromium"
            ) from error
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._browser_context = self._browser.new_context(user_agent=USER_AGENT)

    def _browser_get(self, url: str, referer: str | None = None) -> bytes:
        self._ensure_browser()
        assert self._browser_context is not None
        page = self._browser_context.new_page()
        try:
            if referer:
                page.goto(referer, wait_until="domcontentloaded", timeout=60_000)
            response = page.goto(url, wait_until="commit", timeout=60_000)
            if response is None or not response.ok:
                status = response.status if response is not None else "no response"
                raise DownloadError(f"Browser fetch returned {status} for {url}")
            return response.body()
        finally:
            page.close()

    def get(self, url: str, referer: str | None = None) -> tuple[bytes, str]:
        try:
            return self._http_get(url, referer), "http"
        except DownloadError:
            return self._browser_get(url, referer), "browser"

    def discover(self) -> tuple[list[SourceCandidate], dict[str, str]]:
        candidates: list[SourceCandidate] = []
        methods: dict[str, str] = {}
        for page_url in (COMPSTAT_PAGE, YEAR_END_PAGE):
            content, method = self.get(page_url)
            html = content.decode("utf-8", errors="replace")
            page_candidates = discover_from_html(html, page_url)
            if not page_candidates and method != "browser":
                content = self._browser_get(page_url)
                html = content.decode("utf-8", errors="replace")
                page_candidates = discover_from_html(html, page_url)
                method = "browser"
            candidates.extend(page_candidates)
            methods[page_url] = method
        return candidates, methods

    def download_pdf(self, candidate: SourceCandidate) -> tuple[bytes, str]:
        content, method = self.get(candidate.url, candidate.discovery_page)
        if not content.startswith(b"%PDF-") and method != "browser":
            content = self._browser_get(candidate.url, candidate.discovery_page)
            method = "browser"
        if not content.startswith(b"%PDF-"):
            prefix = content[:80].decode("ascii", errors="replace")
            raise DownloadError(
                f"Expected PDF for {candidate.url}; received {prefix!r}"
            )
        return content, method

    def close(self) -> None:
        if self._browser_context is not None:
            self._browser_context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def __enter__(self) -> "CityClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def document_url_parts(url: str) -> tuple[str | None, str | None]:
    match = re.search(r"/showpublisheddocument/(\d+)/(\d+)", url, re.IGNORECASE)
    return match.groups() if match else (None, None)

