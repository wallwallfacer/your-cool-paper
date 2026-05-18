"""arXiv fetcher: RSS + abs page HTML parsing."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from typing import Iterable

import feedparser
import httpx
from selectolax.parser import HTMLParser

from . import db

log = logging.getLogger(__name__)

# Category aliases (papers.cool 2024.10.17 - the LHS are aliases of the RHS)
CATEGORY_ALIASES = {
    "cs.NA": "math.NA",
    "cs.SY": "eess.SY",
    "math.IT": "cs.IT",
    "math.MP": "math-ph",
    "q-fin.EC": "econ.GN",
    "stat.TH": "math.ST",
}


RSS_URL = "https://rss.arxiv.org/rss/{cat}"
ABS_URL = "https://arxiv.org/abs/{arxiv_id}"

USER_AGENT = "papers-cool-local/0.1 (personal mirror, contact: local)"

_ID_RE = re.compile(r"(\d{4})\.(\d{4,5})(v\d+)?$")


def normalize_arxiv_id(raw: str) -> str:
    """Strip prefixes, normalize 4-digit suffix to 5-digit (1301.3781 -> 1301.03781)."""
    raw = raw.strip()
    raw = raw.removeprefix("arXiv:").removeprefix("arxiv:")
    # remove URL fragments
    if "/" in raw:
        raw = raw.rstrip("/").split("/")[-1]
    if raw.startswith("abs/"):
        raw = raw[4:]
    m = _ID_RE.match(raw)
    if not m:
        return raw
    yymm, num, _ver = m.groups()
    if len(num) == 4:
        num = "0" + num
    return f"{yymm}.{num}"


def id_variants(arxiv_id: str) -> list[str]:
    """Return both 4-digit and 5-digit variants for an arXiv id."""
    norm = normalize_arxiv_id(arxiv_id)
    out = {norm}
    m = _ID_RE.match(norm)
    if m:
        yymm, num, _ver = m.groups()
        if len(num) == 5 and num.startswith("0"):
            out.add(f"{yymm}.{num[1:]}")
        elif len(num) == 4:
            out.add(f"{yymm}.0{num}")
    return list(out)


def _clean_text(s: str) -> str:
    if not s:
        return ""
    return html.unescape(s).replace("\xa0", " ").strip()


def _parse_authors(s: str) -> list[str]:
    if not s:
        return []
    s = _clean_text(s)
    parts = re.split(r",| and ", s)
    return [p.strip() for p in parts if p.strip()]


def _dedup_subjects(subjects: list[str]) -> list[str]:
    """Apply category aliases and dedupe in order."""
    seen: set[str] = set()
    out: list[str] = []
    for sub in subjects:
        sub = sub.strip()
        if not sub:
            continue
        canonical = CATEGORY_ALIASES.get(sub, sub)
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def _extract_arxiv_id_from_link(link: str) -> str | None:
    m = re.search(r"abs/([\w\-\.]+)", link or "")
    if not m:
        return None
    return normalize_arxiv_id(m.group(1))


async def _fetch_rss(client: httpx.AsyncClient, category: str) -> list[dict]:
    """Parse the RSS feed for one category. Returns minimal records."""
    url = RSS_URL.format(cat=category)
    log.info("fetching RSS %s", url)
    r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    results: list[dict] = []
    for entry in parsed.entries:
        link = entry.get("link") or ""
        arxiv_id = _extract_arxiv_id_from_link(link)
        if not arxiv_id:
            continue
        title = _clean_text(entry.get("title", ""))
        # strip the trailing "(arXiv:xxxx)" some feeds include
        title = re.sub(r"\s*\(arXiv:[^)]+\)\s*$", "", title)
        summary = _clean_text(entry.get("summary", "") or entry.get("description", ""))
        # Some arXiv feeds prefix summary with "Abstract: " or "arXiv:xxxx Announce Type: new \nAbstract:"
        summary = re.sub(r"^(arXiv:[\w\.]+\s+)?(Announce Type:\s*\w+\s+)?(Abstract:\s*)?",
                         "", summary, flags=re.IGNORECASE)
        authors_str = ""
        if "authors" in entry and entry.authors:
            authors_str = ", ".join(a.get("name", "") for a in entry.authors)
        elif "author" in entry:
            authors_str = entry.author
        authors = _parse_authors(authors_str)
        published = entry.get("published") or entry.get("updated") or ""
        publish_utc = _parse_pubdate(published)
        results.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": summary,
            "primary_subject": category,
            "subjects": [category],
            "publish_utc": publish_utc,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "version": 1,
        })
    log.info("parsed %d entries for %s", len(results), category)
    return results


def _parse_pubdate(s: str) -> str:
    if not s:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    # feedparser gives us things like "Tue, 12 Nov 2024 00:00:00 -0500"
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _fetch_abs_page(client: httpx.AsyncClient, arxiv_id: str) -> dict | None:
    """Hit the abs page to extract full subjects + author list."""
    url = ABS_URL.format(arxiv_id=arxiv_id)
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("abs fetch failed for %s: %s", arxiv_id, e)
        return None

    tree = HTMLParser(r.text)
    out: dict = {"arxiv_id": arxiv_id}

    title_el = tree.css_first("h1.title")
    if title_el:
        out["title"] = _clean_text(title_el.text(deep=True).replace("Title:", "", 1))

    abs_el = tree.css_first("blockquote.abstract")
    if abs_el:
        out["abstract"] = _clean_text(abs_el.text(deep=True).replace("Abstract:", "", 1))

    authors_el = tree.css_first("div.authors")
    if authors_el:
        names = [_clean_text(a.text()) for a in authors_el.css("a")]
        if names:
            out["authors"] = names

    subjects_td = tree.css_first("td.tablecell.subjects")
    if subjects_td:
        text = _clean_text(subjects_td.text())
        # Format example: "Information Retrieval (cs.IR); Machine Learning (cs.LG)"
        codes = re.findall(r"\(([\w\-\.]+)\)", text)
        if codes:
            out["subjects"] = _dedup_subjects(codes)
            out["primary_subject"] = out["subjects"][0]

    primary_meta = tree.css_first('meta[name="citation_arxiv_id"]')
    if primary_meta:
        meta_id = normalize_arxiv_id(primary_meta.attributes.get("content") or "")
        if meta_id:
            out["arxiv_id"] = meta_id
            out["pdf_url"] = f"https://arxiv.org/pdf/{meta_id}"
            out["abs_url"] = f"https://arxiv.org/abs/{meta_id}"

    pub_meta = tree.css_first('meta[name="citation_date"]')
    if pub_meta:
        out["publish_utc"] = _parse_citation_date(pub_meta.attributes.get("content") or "")

    return out


def _parse_citation_date(s: str) -> str:
    s = s.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def fetch_category(category: str, enrich: bool = True, delay: float = 1.0) -> list[dict]:
    """Fetch RSS + (optionally) enrich every record with abs-page detail."""
    timeout = httpx.Timeout(30, connect=15)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        records = await _fetch_rss(client, category)
        if enrich:
            for rec in records:
                detail = await _fetch_abs_page(client, rec["arxiv_id"])
                if detail:
                    rec.update({k: v for k, v in detail.items() if v})
                await asyncio.sleep(delay)
    # Ensure publish_utc reflects the announce-date so daily lists work
    return records


async def fetch_categories(
    categories: Iterable[str], enrich: bool = True, delay: float = 1.0
) -> dict[str, int]:
    """Fetch and persist multiple categories. Returns {category: written_count}."""
    out: dict[str, int] = {}
    for cat in categories:
        records = await fetch_category(cat, enrich=enrich, delay=delay)
        written = db.upsert_papers(records)
        # Group by publish date for fetch_log
        today = datetime.now(timezone.utc).date().isoformat()
        db.record_fetch(cat, today, written)
        out[cat] = written
    return out


async def fetch_single_paper(arxiv_id: str) -> dict | None:
    """Fetch a single paper by id (used by lazy /arxiv/<id> route)."""
    arxiv_id = normalize_arxiv_id(arxiv_id)
    timeout = httpx.Timeout(30, connect=15)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        detail = await _fetch_abs_page(client, arxiv_id)
    if not detail:
        return None
    detail.setdefault("title", "")
    detail.setdefault("abstract", "")
    detail.setdefault("authors", [])
    detail.setdefault("subjects", [])
    detail.setdefault("primary_subject", detail["subjects"][0] if detail["subjects"] else "")
    detail.setdefault("publish_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    detail.setdefault("pdf_url", f"https://arxiv.org/pdf/{arxiv_id}")
    detail.setdefault("abs_url", f"https://arxiv.org/abs/{arxiv_id}")
    detail.setdefault("version", 1)
    db.upsert_papers([detail])
    return detail
