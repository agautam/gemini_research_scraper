"""Command-line interface: `login`, `run`, and `serve`."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import typer
from playwright.sync_api import Error as PlaywrightError

from . import selectors as S
from .browser import find_visible, gemini_page, has_google_session
from .config import Settings
from .output import save_result
from .research import NotLoggedInError, run_research

app = typer.Typer(
    name="gemini-research",
    help="Run Gemini Deep Research from the command line and save the report.",
    no_args_is_help=True,
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _settings(profile_dir: Optional[Path], headless: Optional[bool]) -> Settings:
    s = Settings.from_env()
    if profile_dir is not None:
        s.profile_dir = profile_dir
    if headless is not None:
        s.headless = headless
    return s


@app.command()
def login(
    profile_dir: Optional[Path] = typer.Option(
        None, help="Browser profile directory (defaults to ~/.gemini-research-scraper)."
    ),
    timeout_min: int = typer.Option(10, help="How long to wait for you to sign in."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Open a browser window so you can sign in to Google once.

    The session is stored in the persistent profile and reused by `run`.
    """
    _setup_logging(verbose)
    settings = _settings(profile_dir, headless=False)  # login must be headful
    typer.echo("A Chrome window will open on gemini.google.com. Sign in to your "
               "Google account there (in the noVNC tab if running in Docker).")
    with gemini_page(settings) as page:
        page.goto(settings.base_url, wait_until="domcontentloaded")
        typer.echo(f"Waiting up to {timeout_min} min for you to finish signing in...")
        deadline = time.monotonic() + timeout_min * 60
        signed_in = False
        while time.monotonic() < deadline:
            # Google's auth cookies are the ground truth - they only exist
            # for a signed-in session, no matter what the page is rendering.
            # The DOM conditions on top guard against half-loaded states.
            try:
                if (
                    has_google_session(page)
                    and "accounts.google.com" not in page.url
                    and find_visible(page, S.SIGN_IN_BUTTON) is None
                    and find_visible(page, S.PROMPT_INPUT) is not None
                ):
                    signed_in = True
                    break
            except PlaywrightError:
                pass  # page was mid-navigation; try again
            time.sleep(2)
        if not signed_in:
            typer.secho(
                f"Not signed in after {timeout_min} min - giving up. "
                "Re-run this command to try again.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        # Let session cookies/storage settle before tearing the browser down.
        page.wait_for_timeout(3000)
    typer.secho(
        f"Signed in. Session saved to {settings.profile_dir}", fg=typer.colors.GREEN
    )


@app.command()
def run(
    query: str = typer.Argument(..., help="The research question to submit."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output file path (extension picks the format); defaults to "
             "./research_output/<timestamp>-<title>.md",
    ),
    fmt: str = typer.Option(
        "md,html", "--format", "-f", help="Comma-separated formats: md, html."
    ),
    profile_dir: Optional[Path] = typer.Option(None),
    headless: Optional[bool] = typer.Option(
        None, help="Run the browser headless (headful is more reliable)."
    ),
    timeout_min: Optional[int] = typer.Option(
        None, help="Max minutes to wait for the research to finish."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run one Deep Research query end-to-end and save the report."""
    _setup_logging(verbose)
    settings = _settings(profile_dir, headless)
    if timeout_min is not None:
        settings.research_timeout_s = timeout_min * 60

    try:
        result = run_research(query, settings)
    except NotLoggedInError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=2)

    if output is not None:
        formats = (output.suffix.lstrip(".") or "md",)
        paths = save_result(
            result, output.parent if output.parent != Path("") else Path("."),
            formats=formats, stem=output.stem,
        )
    else:
        formats = tuple(f.strip() for f in fmt.split(",") if f.strip())
        paths = save_result(result, settings.output_dir, formats=formats)

    typer.secho(f"Report: {result.title}", fg=typer.colors.GREEN)
    for p in paths:
        typer.echo(f"  -> {p.resolve()}")


def _open_and_let_user_navigate(page, settings, url: Optional[str], wait_s: int) -> None:
    page.goto(url or settings.base_url, wait_until="domcontentloaded")
    if not url:
        typer.secho(
            f"You have {wait_s}s: in the noVNC tab, click the conversation that "
            "holds the finished research (and open the report if it's collapsed).",
            fg=typer.colors.YELLOW,
        )
        page.wait_for_timeout(wait_s * 1000)
    else:
        page.wait_for_timeout(8000)


@app.command()
def inspect(
    url: Optional[str] = typer.Option(None, help="Chat URL to open directly."),
    wait_s: int = typer.Option(
        30, help="Seconds you get to navigate to the right chat via noVNC."
    ),
    profile_dir: Optional[Path] = typer.Option(None),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Diagnostic: dump what's visible on the page and which of our selector
    groups match it. Paste the output when reporting a UI mismatch."""
    _setup_logging(verbose)
    settings = _settings(profile_dir, headless=None)
    with gemini_page(settings) as page:
        _open_and_let_user_navigate(page, settings, url, wait_s)
        info = page.evaluate(
            """() => {
              const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              const buttons = [...document.querySelectorAll('button,[role=button]')].filter(vis)
                .map(b => [b.getAttribute('aria-label'), (b.textContent||'').trim().slice(0,50)]).slice(0, 80);
              const tags = [...new Set([...document.querySelectorAll('*')].filter(vis)
                .map(e => e.tagName.toLowerCase()).filter(t => t.includes('-')))]
                .filter(t => /research|report|immersive|panel|message|response|canvas|doc|editor|toolbar/.test(t));
              const headings = [...document.querySelectorAll('h1,h2')].filter(vis)
                .map(h => h.tagName + ': ' + (h.textContent||'').trim().slice(0,70)).slice(0, 10);
              return {buttons, customTags: tags, headings, url: location.href};
            }"""
        )
        import json

        typer.echo("=== PAGE DUMP (paste this back when reporting) ===")
        typer.echo(json.dumps(info, indent=1))
        typer.echo("=== SELECTOR GROUP MATCHES ===")
        groups = [
            ("RESEARCH_COMPLETE", S.RESEARCH_COMPLETE),
            ("RESEARCH_IN_PROGRESS", S.RESEARCH_IN_PROGRESS),
            ("START_RESEARCH_BUTTON", S.START_RESEARCH_BUTTON),
            ("REPORT_CONTAINER", S.REPORT_CONTAINER),
            ("REPORT_TITLE", S.REPORT_TITLE),
        ]
        for name, group in groups:
            loc = find_visible(page, group)
            typer.echo(f"{name}: {'MATCH' if loc is not None else 'no match'}")


@app.command()
def extract(
    chat: Optional[str] = typer.Argument(
        None,
        help="Chat URL (https://gemini.google.com/app/<id>) or bare chat id. "
             "Omit it to pick the chat by hand via noVNC during a countdown.",
    ),
    query_label: Optional[str] = typer.Option(
        None, "--label", help="Recorded as the query in the document header."
    ),
    wait_s: int = typer.Option(
        30, help="Seconds to navigate via noVNC when no chat is given."
    ),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    profile_dir: Optional[Path] = typer.Option(None),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Scrape a finished Deep Research report from any existing chat - also
    ones that were run by hand, outside this service - and save it."""
    _setup_logging(verbose)
    from .research import ensure_report_open, extract_from_chat, extract_report

    settings = _settings(profile_dir, headless=None)
    if chat is not None:
        result = extract_from_chat(chat, settings, query_label)
    else:
        with gemini_page(settings) as page:
            _open_and_let_user_navigate(page, settings, None, wait_s)
            ensure_report_open(page)
            result = extract_report(
                page, settings, query_label or "manually extracted research"
            )
    if output is not None:
        paths = save_result(
            result, output.parent if str(output.parent) else Path("."),
            formats=(output.suffix.lstrip(".") or "md",), stem=output.stem,
        )
    else:
        paths = save_result(result, settings.output_dir, formats=("md", "html"))
    typer.secho(f"Report: {result.title}", fg=typer.colors.GREEN)
    for p in paths:
        typer.echo(f"  -> {p.resolve()}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start the HTTP API (POST /research, GET /research/{id}, .../document)."""
    _setup_logging(verbose)
    import uvicorn

    from .server import create_app

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()
