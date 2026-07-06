"""Turn a ResearchResult into files on disk (Markdown and/or HTML)."""

from __future__ import annotations

import re
from pathlib import Path

from .research import ResearchResult

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "research"


def _markdown_document(result: ResearchResult) -> str:
    header = (
        f"---\n"
        f"title: {result.title}\n"
        f"query: {result.query}\n"
        f"source: {result.chat_url}\n"
        f"started: {result.started_at.isoformat()}\n"
        f"finished: {result.finished_at.isoformat()}\n"
        f"generator: gemini-research-scraper\n"
        f"---\n\n"
    )
    return header + result.markdown + "\n"


def _html_document(result: ResearchResult) -> str:
    return (
        "<!doctype html>\n<html>\n<head>\n"
        f"<meta charset='utf-8'>\n<title>{result.title}</title>\n"
        "</head>\n<body>\n"
        f"{result.html}\n"
        "</body>\n</html>\n"
    )


def save_result(
    result: ResearchResult,
    out_dir: Path,
    formats: tuple[str, ...] = ("md",),
    stem: str | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or (
        f"{result.finished_at.strftime('%Y%m%d-%H%M%S')}-{slugify(result.title)}"
    )
    written: list[Path] = []
    if "md" in formats:
        path = out_dir / f"{stem}.md"
        path.write_text(_markdown_document(result), encoding="utf-8")
        written.append(path)
    if "html" in formats:
        path = out_dir / f"{stem}.html"
        path.write_text(_html_document(result), encoding="utf-8")
        written.append(path)
    return written
