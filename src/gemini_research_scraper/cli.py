"""Command-line interface: `login`, `run`, and `serve`."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from . import selectors as S
from .browser import find_visible, gemini_page
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
    typer.echo("A Chrome window will open. Sign in to your Google account on "
               "gemini.google.com, then leave the window alone.")
    with gemini_page(settings) as page:
        page.goto(settings.base_url, wait_until="domcontentloaded")
        deadline_ms = timeout_min * 60 * 1000
        try:
            # Signed-in state == the prompt composer is visible.
            page.wait_for_selector(
                "div[contenteditable='true']", timeout=deadline_ms, state="visible"
            )
        except Exception:
            typer.secho("Timed out waiting for sign-in.", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        if find_visible(page, S.SIGN_IN_BUTTON) is not None:
            typer.secho("Still signed out - please retry.", fg=typer.colors.RED)
            raise typer.Exit(code=1)
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
        "md", "--format", "-f", help="Comma-separated formats: md, html."
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
