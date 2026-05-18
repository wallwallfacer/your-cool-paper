"""Smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from papers_cool import db
from papers_cool.arxiv import id_variants, normalize_arxiv_id


def test_normalize_id_padding():
    assert normalize_arxiv_id("1301.3781") == "1301.03781"
    assert normalize_arxiv_id("1301.03781") == "1301.03781"
    assert normalize_arxiv_id("arXiv:2305.01234v2") == "2305.01234"
    assert normalize_arxiv_id("https://arxiv.org/abs/2305.01234") == "2305.01234"


def test_id_variants_roundtrip():
    v = id_variants("1301.3781")
    assert "1301.03781" in v
    assert "1301.3781" in v


def test_db_upsert_and_list():
    db.init_db()
    records = [
        {
            "arxiv_id": "2401.00001",
            "title": "Test Paper One",
            "authors": ["Alice"],
            "abstract": "About retrieval and DPO.",
            "primary_subject": "cs.IR",
            "subjects": ["cs.IR"],
            "publish_utc": "2026-05-11T00:00:00+00:00",
            "pdf_url": "https://arxiv.org/pdf/2401.00001",
            "abs_url": "https://arxiv.org/abs/2401.00001",
            "version": 1,
        }
    ]
    assert db.upsert_papers(records) == 1
    rows = db.list_papers_by_categories(["cs.IR"])
    assert len(rows) == 1
    assert rows[0]["title"] == "Test Paper One"


def test_fts_search():
    db.init_db()
    db.upsert_papers(
        [
            {
                "arxiv_id": "2401.00002",
                "title": "Dense Passage Retrieval",
                "authors": ["Bob"],
                "abstract": "Embedding-based retriever",
                "primary_subject": "cs.IR",
                "subjects": ["cs.IR"],
                "publish_utc": "2026-05-11T00:00:00+00:00",
                "pdf_url": "https://arxiv.org/pdf/2401.00002",
                "abs_url": "https://arxiv.org/abs/2401.00002",
                "version": 1,
            }
        ]
    )
    hits = db.search_papers("retrieval")
    assert any(h["arxiv_id"] == "2401.00002" for h in hits)


def test_index_renders():
    from papers_cool.main import app

    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "papers.cool" in r.text


def test_list_route_empty_render():
    from papers_cool.main import app

    with TestClient(app) as client:
        # an unfetched category should still render (lazy fetch may fail in CI: that's fine)
        r = client.get("/arxiv/cs.IR?date=2099-01-01")
        assert r.status_code == 200


def test_healthz():
    from papers_cool.main import app

    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["ok"] is True


def test_invalid_category_rejected():
    from papers_cool.main import app

    with TestClient(app) as client:
        r = client.get("/arxiv/bogus@#$")
        assert r.status_code == 400


def test_summary_save_get_roundtrip():
    db.init_db()
    db.save_summary("2401.00099", "zh", "gpt-4o-mini", "**Hello**")
    got = db.get_summary("2401.00099", "zh")
    assert got is not None
    assert got["content"] == "**Hello**"
