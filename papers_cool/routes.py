"""HTTP routes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from . import ai, arxiv as arxiv_mod, db, scheduler
from .config import get_settings

log = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["base_path"] = get_settings().base_path_norm

router = APIRouter()


def _parse_categories(cats: str) -> list[str]:
    """Parse 'cs.IR,cs.LG' into a list of category codes (sanitized)."""
    parts = [c.strip() for c in cats.split(",") if c.strip()]
    out: list[str] = []
    for p in parts:
        if not _valid_category(p):
            raise HTTPException(status_code=400, detail=f"invalid category: {p}")
        out.append(p)
    return out


def _valid_category(c: str) -> bool:
    import re

    return bool(re.match(r"^[a-zA-Z\-]+(\.[A-Za-z\-]+)?$", c))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "categories": settings.categories,
            "default_lang": settings.default_ai_lang,
        },
    )


@router.get("/arxiv/{cats}", response_class=HTMLResponse)
async def arxiv_list(
    request: Request,
    cats: str,
    date: str | None = Query(default=None),
):
    settings = get_settings()
    # Support `cs.IR,cs.LG` and (single) arxiv id lookup `2602.24277`
    if _looks_like_arxiv_id(cats):
        return await _paper_detail(request, cats)

    categories = _parse_categories(cats)

    # Lazy fetch any category missing today's data (parallel).
    await asyncio.gather(
        *[scheduler.lazy_fetch_if_needed(c) for c in categories],
        return_exceptions=True,
    )

    papers = db.list_papers_by_categories(categories, date=date)
    _apply_cached_translations(papers, settings.default_ai_lang)
    if not papers and date is None:
        # nothing yet - render empty list with helpful message
        pass

    target_date = (
        date
        or (papers[0]["publish_utc"][:10] if papers else None)
        or db.latest_publish_date(categories)
    )
    return templates.TemplateResponse(
        request,
        "list.html",
        {
            "papers": papers,
            "categories": categories,
            "category_slug": ",".join(categories),
            "date": target_date,
            "available_dates": db.available_dates(categories),
            "default_lang": settings.default_ai_lang,
            "all_categories": settings.categories,
        },
    )


def _apply_cached_translations(papers: list[dict], lang: str) -> None:
    """Replace each paper's abstract with the cached translation when present."""
    if not papers or lang == "en":
        return
    for p in papers:
        cached = db.get_abstract_translation(p["arxiv_id"], lang)
        if cached:
            p["abstract"] = cached
            p["abstract_translated_lang"] = lang


def _looks_like_arxiv_id(s: str) -> bool:
    import re

    return bool(re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", s))


async def _paper_detail(request: Request, raw_id: str) -> HTMLResponse:
    arxiv_id = arxiv_mod.normalize_arxiv_id(raw_id)
    paper = db.get_paper(arxiv_id)
    if not paper:
        # Try the 4-digit variant
        for variant in arxiv_mod.id_variants(arxiv_id):
            paper = db.get_paper(variant)
            if paper:
                arxiv_id = variant
                break
    if not paper:
        # lazy fetch single paper
        try:
            paper = await arxiv_mod.fetch_single_paper(arxiv_id)
        except Exception:
            log.exception("single paper fetch failed: %s", arxiv_id)
    if not paper:
        raise HTTPException(status_code=404, detail=f"paper {arxiv_id} not found")

    settings = get_settings()
    _apply_cached_translations([paper], settings.default_ai_lang)
    return templates.TemplateResponse(
        request,
        "list.html",
        {
            "papers": [paper],
            "categories": [paper["primary_subject"]],
            "category_slug": paper["primary_subject"],
            "date": paper["publish_utc"][:10],
            "available_dates": [],
            "default_lang": settings.default_ai_lang,
            "all_categories": settings.categories,
            "single_view": True,
        },
    )


# ---- JSON / SSE endpoints ----------------------------------------------------


@router.get("/api/papers/{cats}")
async def api_papers(cats: str, date: str | None = None):
    categories = _parse_categories(cats)
    await asyncio.gather(
        *[scheduler.lazy_fetch_if_needed(c) for c in categories],
        return_exceptions=True,
    )
    papers = db.list_papers_by_categories(categories, date=date)
    return {"papers": papers, "date": date}


@router.get("/api/search")
async def api_search(q: str = Query(min_length=1, max_length=200), limit: int = 100):
    papers = db.search_papers(q, limit=limit)
    return {"query": q, "papers": papers}


@router.get("/api/related/{arxiv_id}")
async def api_related(arxiv_id: str):
    """v1: redirect-style related papers - just link to arXiv's similar page.

    The endpoint returns metadata; the front-end opens the arXiv labs URL directly,
    but we still want a JSON response for future expansion.
    """
    norm = arxiv_mod.normalize_arxiv_id(arxiv_id)
    paper = db.get_paper(norm)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")
    # Use FTS5 against title tokens for a local recommendation list
    title = paper["title"]
    tokens = [t for t in title.split() if len(t) > 3][:6]
    query = " ".join(tokens) if tokens else title
    suggestions = [p for p in db.search_papers(query, limit=20) if p["arxiv_id"] != norm][:10]
    return {
        "arxiv_id": norm,
        "arxiv_similar_url": f"https://arxiv.org/list/{paper['primary_subject']}/recent",
        "labs_url": f"https://www.arxiv-sanity-lite.com/?rank=pid&pid={norm}",
        "suggestions": suggestions,
    }


@router.get("/api/abstract/{arxiv_id}")
async def api_abstract(arxiv_id: str, lang: str | None = None, force: int = 0):
    settings = get_settings()
    lang = (lang or settings.default_ai_lang).lower()
    if lang not in ("zh", "en"):
        lang = "en"
    norm = arxiv_mod.normalize_arxiv_id(arxiv_id)
    try:
        text = await ai.translate_abstract(norm, lang, force=bool(force))
    except ValueError:
        raise HTTPException(status_code=404, detail="paper not found")
    return {"arxiv_id": norm, "lang": lang, "abstract": text}


@router.get("/api/ai/{arxiv_id}")
async def api_ai(arxiv_id: str, lang: str | None = None, force: int = 0):
    settings = get_settings()
    lang = (lang or settings.default_ai_lang).lower()
    if lang not in ("zh", "en"):
        lang = "en"
    norm = arxiv_mod.normalize_arxiv_id(arxiv_id)

    async def gen() -> AsyncIterator[bytes]:
        async for chunk in ai.stream_summary(norm, lang, force=bool(force)):
            # Plain text stream (the client just concatenates into markdown)
            yield chunk.encode("utf-8")

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


@router.post("/api/fetch/{cats}")
async def api_fetch(cats: str):
    categories = _parse_categories(cats)
    counts = await arxiv_mod.fetch_categories(categories, enrich=True, delay=1.0)
    return {"fetched": counts}


@router.get("/healthz")
async def health():
    return {"ok": True}
