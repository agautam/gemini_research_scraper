"""The Deep Research flow itself: log-in check, enable Deep Research, submit
the query, approve the generated plan, wait out the (long) research run, and
scrape the finished report."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from markdownify import markdownify
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from . import selectors as S
from .browser import find_visible, gemini_page, resolve, wait_visible
from .config import Settings

log = logging.getLogger(__name__)


class NotLoggedInError(RuntimeError):
    """The persistent profile has no Google session. Run `gemini-research login`."""


class ResearchFailedError(RuntimeError):
    """Gemini reported an error while running the research."""


@dataclass
class ResearchResult:
    query: str
    title: str
    markdown: str
    html: str
    chat_url: str
    started_at: datetime
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# Individual steps
# --------------------------------------------------------------------------

def open_gemini(page: Page, settings: Settings) -> None:
    log.info("Opening %s", settings.base_url)
    page.goto(settings.base_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=settings.nav_timeout_s * 1000)


def assert_logged_in(page: Page, settings: Settings) -> None:
    if "accounts.google.com" in page.url:
        raise NotLoggedInError(
            "Redirected to Google sign-in. Run `gemini-research login` first."
        )
    if find_visible(page, S.SIGN_IN_BUTTON) is not None:
        raise NotLoggedInError(
            "Gemini shows a 'Sign in' button. Run `gemini-research login` first."
        )
    # Positive check: the prompt composer must exist for a signed-in session.
    wait_visible(page, S.PROMPT_INPUT, settings.nav_timeout_s, "the prompt input")
    log.info("Logged-in Gemini session confirmed.")


def enable_deep_research(page: Page, settings: Settings) -> None:
    """Deep Research is either a chip next to the composer or an entry in the
    composer's 'Tools' menu, depending on the rollout Gemini serves."""
    chip = find_visible(page, S.DEEP_RESEARCH_CHIP)
    if chip is not None:
        chip.click()
        log.info("Enabled Deep Research via composer chip.")
    else:
        tools = wait_visible(page, S.TOOLS_BUTTON, 15, "the 'Tools' menu button")
        tools.click()
        item = wait_visible(
            page, S.DEEP_RESEARCH_MENU_ITEM, 10, "the 'Deep Research' menu item"
        )
        item.click()
        log.info("Enabled Deep Research via Tools menu.")
    page.wait_for_timeout(1000)
    if find_visible(page, S.DEEP_RESEARCH_ACTIVE) is None:
        log.warning(
            "Could not confirm Deep Research is active; continuing anyway. "
            "If the result is a plain chat answer, update selectors.py."
        )


def submit_query(page: Page, settings: Settings, query: str) -> None:
    box = wait_visible(page, S.PROMPT_INPUT, settings.nav_timeout_s, "the prompt input")
    box.click()
    # insert_text handles multi-line queries without Enter submitting early.
    page.keyboard.insert_text(query)
    send = wait_visible(page, S.SEND_BUTTON, 15, "the send button")
    send.click()
    log.info("Query submitted (%d chars).", len(query))


def approve_plan(page: Page, settings: Settings) -> None:
    """Gemini answers a Deep Research query with a plan plus a 'Start research'
    button; approving means clicking it."""
    log.info("Waiting for the research plan (up to %ss)...", settings.plan_timeout_s)
    start = wait_visible(
        page, S.START_RESEARCH_BUTTON, settings.plan_timeout_s,
        "the 'Start research' button (the research plan)",
    )
    start.click()
    log.info("Research plan approved - research started.")


def wait_for_completion(page: Page, settings: Settings) -> None:
    log.info(
        "Waiting for research to finish (up to %s min)...",
        settings.research_timeout_s // 60,
    )
    deadline = time.monotonic() + settings.research_timeout_s
    last_note = 0.0
    while time.monotonic() < deadline:
        if find_visible(page, S.RESEARCH_FAILED) is not None:
            raise ResearchFailedError("Gemini reported that the research failed.")
        if find_visible(page, S.RESEARCH_COMPLETE) is not None:
            log.info("Research complete.")
            return
        now = time.monotonic()
        if now - last_note > 60:
            in_progress = find_visible(page, S.RESEARCH_IN_PROGRESS) is not None
            log.info(
                "Still %s...", "researching" if in_progress else "waiting for output"
            )
            last_note = now
        time.sleep(settings.poll_interval_s)
    raise TimeoutError(
        f"Research did not finish within {settings.research_timeout_s}s."
    )


def extract_report(page: Page, settings: Settings, query: str) -> ResearchResult:
    # Give the report panel a moment to render fully after completion.
    page.wait_for_timeout(3000)

    container = None
    for cand in S.REPORT_CONTAINER:
        try:
            loc = resolve(page, cand)
            if cand == ("css", "message-content"):
                loc = page.locator("message-content").last  # newest chat message
            if loc.is_visible():
                container = loc
                break
        except PlaywrightError:
            continue
    if container is None:
        raise ResearchFailedError(
            "Research finished but no report container was found; "
            "update REPORT_CONTAINER in selectors.py."
        )

    html = container.inner_html()
    md = markdownify(html, heading_style="ATX", bullets="-").strip()
    if not md:
        raise ResearchFailedError("Report container was empty.")

    title_loc = find_visible(page, S.REPORT_TITLE)
    if title_loc is not None:
        title = title_loc.inner_text().strip()
    else:
        first_line = md.splitlines()[0].lstrip("# ").strip()
        title = first_line or query[:80]

    log.info("Extracted report: %r (%d chars of Markdown).", title, len(md))
    return ResearchResult(
        query=query,
        title=title,
        markdown=md,
        html=html,
        chat_url=page.url,
        started_at=datetime.now(timezone.utc),  # overwritten by run_research
    )


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

def run_research(query: str, settings: Settings | None = None) -> ResearchResult:
    """End-to-end Deep Research run. Blocking; typically 5-25 minutes."""
    settings = settings or Settings.from_env()
    started_at = datetime.now(timezone.utc)
    with gemini_page(settings) as page:
        open_gemini(page, settings)
        assert_logged_in(page, settings)
        enable_deep_research(page, settings)
        submit_query(page, settings, query)
        approve_plan(page, settings)
        wait_for_completion(page, settings)
        result = extract_report(page, settings, query)
        result.started_at = started_at
        return result
