"""CLI entrypoint."""

from __future__ import annotations

import asyncio
import json

import click

from . import arxiv as arxiv_mod
from . import db
from .config import get_settings


@click.group()
def main() -> None:
    """papers.cool local CLI."""


@main.command("init-db")
def init_db_cmd() -> None:
    """Initialize the SQLite database (idempotent)."""
    db.init_db()
    click.echo(f"db ready at {get_settings().db_path}")


@main.command("fetch")
@click.argument("categories", nargs=-1, required=True)
@click.option("--no-enrich", is_flag=True, help="Skip the abs-page detail fetch")
@click.option("--delay", default=1.0, help="Seconds between detail-page fetches")
def fetch_cmd(categories: tuple[str, ...], no_enrich: bool, delay: float) -> None:
    """Fetch one or more arXiv categories and persist to DB."""
    cats = list(categories)
    if not cats:
        cats = get_settings().categories
    click.echo(f"fetching {cats}")
    counts = asyncio.run(arxiv_mod.fetch_categories(cats, enrich=not no_enrich, delay=delay))
    click.echo(json.dumps(counts, indent=2))


@main.command("stats")
def stats_cmd() -> None:
    """Print quick counts per category."""
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT primary_subject, COUNT(*) AS n,
                   MIN(substr(publish_utc,1,10)) AS first_date,
                   MAX(substr(publish_utc,1,10)) AS last_date
            FROM papers GROUP BY primary_subject ORDER BY n DESC
            """
        ).fetchall()
    for r in rows:
        click.echo(f"{r['primary_subject']:<10} n={r['n']:<6} {r['first_date']} -> {r['last_date']}")


@main.command("serve")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
def serve_cmd(host: str | None, port: int | None) -> None:
    """Run the FastAPI server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "papers_cool.main:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
