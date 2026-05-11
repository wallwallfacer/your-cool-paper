"""OpenAI-compatible AI summary streaming."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

import httpx
from openai import AsyncOpenAI

from . import db
from .config import get_settings

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are an academic paper assistant. Below is a paper's \
metadata and a text extract. Output an FAQ-style summary in {language} covering:

Q1: What problem does this paper solve?
Q2: What is the core method?
Q3: Key novelty vs. prior work?
Q4: Experimental setup and main results?
Q5: Limitations and future directions?

Requirements:
- Wrap formulas in LaTeX ($...$ or $$...$$).
- Use Markdown (tables, lists, headings).
- Stay under 800 words.
- No pleasantries or restating the question.

[Title]: {title}
[Authors]: {authors}
[Primary subject]: {subject}
[Abstract]:
{abstract}

[Full Text Extract]:
{full_text}
"""


LANGUAGE_NAMES = {"zh": "Chinese", "en": "English"}


def _client() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(
        api_key=s.openai_api_key,
        base_url=s.openai_base_url,
        timeout=s.openai_timeout,
    )


def _build_prompt(paper: dict, lang: str, full_text: str) -> str:
    return PROMPT_TEMPLATE.format(
        language=LANGUAGE_NAMES.get(lang, "English"),
        title=paper.get("title", ""),
        authors=", ".join(paper.get("authors", []))[:1000],
        subject=paper.get("primary_subject", ""),
        abstract=paper.get("abstract", ""),
        full_text=full_text[:32000] if full_text else "(PDF not available)",
    )


async def _download_pdf_text(arxiv_id: str, pdf_url: str) -> str:
    """Download the PDF and extract first ~8K of text. Cached on disk."""
    cache = get_settings().pdf_cache_dir / f"{arxiv_id}.txt"
    if cache.exists():
        try:
            return cache.read_text(encoding="utf-8")
        except OSError:
            pass

    text = ""
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(pdf_url, headers={"User-Agent": "papers-cool-local/0.1"})
            r.raise_for_status()
            pdf_bytes = r.content
    except httpx.HTTPError as e:
        log.warning("pdf download failed for %s: %s", arxiv_id, e)
        return ""

    try:
        from pypdf import PdfReader  # local import keeps startup snappy
        import io

        reader = PdfReader(io.BytesIO(pdf_bytes))
        chunks: list[str] = []
        for page in reader.pages[:15]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
            if sum(len(c) for c in chunks) > 40000:
                break
        text = "\n\n".join(chunks)
        text = re.sub(r"\n{3,}", "\n\n", text)
    except Exception as e:
        log.warning("pdf parse failed for %s: %s", arxiv_id, e)
        text = ""

    if text:
        try:
            cache.write_text(text, encoding="utf-8")
        except OSError:
            pass
    return text


async def stream_summary(
    arxiv_id: str,
    lang: str,
    force: bool = False,
) -> AsyncIterator[str]:
    """Yield markdown chunks. Also saves the final content into ai_summaries."""
    paper = db.get_paper(arxiv_id)
    if not paper:
        yield f"**Error:** paper `{arxiv_id}` not found.\n"
        return

    settings = get_settings()
    if not force:
        cached = db.get_summary(arxiv_id, lang)
        if cached:
            text = cached["content"]
            chunk_size = 256
            for i in range(0, len(text), chunk_size):
                yield text[i : i + chunk_size]
                await asyncio.sleep(0)
            return

    full_text = await _download_pdf_text(arxiv_id, paper["pdf_url"])
    prompt = _build_prompt(paper, lang, full_text)

    if settings.openai_api_key in ("", "sk-missing", "sk-replace-me"):
        msg = (
            "**AI not configured.**\n\n"
            "Set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` in `~/.papers-cool/.env`.\n"
        )
        yield msg
        return

    client = _client()
    collected: list[str] = []
    try:
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
            if delta:
                collected.append(delta)
                yield delta
    except Exception as e:
        log.exception("AI streaming error for %s", arxiv_id)
        err = f"\n\n**[stream error]** `{type(e).__name__}: {e}`\n"
        collected.append(err)
        yield err
        return

    content = "".join(collected).strip()
    if content:
        db.save_summary(arxiv_id, lang, settings.openai_model, content)


