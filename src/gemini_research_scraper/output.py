"""Turn a ResearchResult into files on disk.

Default layout: one subfolder per research run -

    <out_dir>/<timestamp>-<title-slug>/
        report.md            # human-readable, with metadata frontmatter
        report.html          # raw scraped HTML
        report.compact.md    # token-optimized for feeding into an LLM
        sources.md           # citation list (when the page exposed one)
        thinking.md          # model reasoning (when the page exposed it)

When an explicit output stem is given (CLI `-o report.md`), the old flat
single-file behavior is kept.
"""

from __future__ import annotations

import re
from pathlib import Path

from .research import ResearchResult

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "research"


def compact_markdown(md: str) -> str:
    """Token-optimized rendering: same content, less markup. Drops images,
    link URLs (keeps anchor text), emphasis markers, horizontal rules, and
    excess blank lines - the things that cost tokens without informing an
    LLM. Structure (headings, lists, tables) is kept."""
    text = md
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)              # images
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)          # links -> text
    text = re.sub(r"\*\*\*([^*]+)\*\*\*", r"\1", text)            # bold-italic
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)                # bold
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", text)  # italic
    text = re.sub(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", "", text, flags=re.M)  # hrs
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)               # trailing ws
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _frontmatter(result: ResearchResult) -> str:
    return (
        f"---\n"
        f"title: {result.title}\n"
        f"query: {result.query}\n"
        f"source: {result.chat_url}\n"
        f"started: {result.started_at.isoformat()}\n"
        f"finished: {result.finished_at.isoformat()}\n"
        f"generator: gemini-research-scraper\n"
        f"---\n\n"
    )


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
    formats: tuple[str, ...] = ("md", "html"),
    stem: str | None = None,
) -> list[Path]:
    written: list[Path] = []

    if stem is not None:
        # Explicit single-file mode (CLI -o): flat files next to each other.
        out_dir.mkdir(parents=True, exist_ok=True)
        if "md" in formats:
            path = out_dir / f"{stem}.md"
            path.write_text(_frontmatter(result) + result.markdown + "\n",
                            encoding="utf-8")
            written.append(path)
        if "html" in formats:
            path = out_dir / f"{stem}.html"
            path.write_text(_html_document(result), encoding="utf-8")
            written.append(path)
        return written

    folder = out_dir / (
        f"{result.finished_at.strftime('%Y%m%d-%H%M%S')}-{slugify(result.title)}"
    )
    folder.mkdir(parents=True, exist_ok=True)

    if "md" in formats:
        path = folder / "report.md"
        path.write_text(_frontmatter(result) + result.markdown + "\n",
                        encoding="utf-8")
        written.append(path)
    if "html" in formats:
        path = folder / "report.html"
        path.write_text(_html_document(result), encoding="utf-8")
        written.append(path)

    path = folder / "report.compact.md"
    path.write_text(
        f"# {result.title}\n\nQuery: {result.query}\n\n"
        + compact_markdown(result.markdown),
        encoding="utf-8",
    )
    written.append(path)

    if result.sources_markdown:
        path = folder / "sources.md"
        path.write_text(result.sources_markdown, encoding="utf-8")
        written.append(path)
    if result.thinking_markdown:
        path = folder / "thinking.md"
        path.write_text(result.thinking_markdown, encoding="utf-8")
        written.append(path)
    return written
