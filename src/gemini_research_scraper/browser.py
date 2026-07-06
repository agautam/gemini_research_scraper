"""Browser lifecycle: a persistent Chrome profile so the Google login
survives between runs, plus locator helpers for the candidate-selector
scheme defined in selectors.py."""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from typing import Iterator, Sequence

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, sync_playwright

from .config import Settings
from .selectors import Candidate

log = logging.getLogger(__name__)


@contextmanager
def gemini_page(settings: Settings) -> Iterator[Page]:
    """Launch a persistent-profile browser and yield a page. The profile can
    only be attached to one browser at a time, so callers must not overlap."""
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    # Reduces the most obvious automation fingerprint; Google may otherwise
    # refuse sign-in inside an automated browser.
    args = ["--disable-blink-features=AutomationControlled"]
    if settings.no_sandbox:
        args += ["--no-sandbox", "--disable-dev-shm-usage"]
    with sync_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=str(settings.profile_dir),
            headless=settings.headless,
            viewport={"width": 1440, "height": 900},
            args=args,
            ignore_default_args=["--enable-automation"],
        )
        context = None
        if settings.browser_channel:
            try:
                context = p.chromium.launch_persistent_context(
                    channel=settings.browser_channel, **launch_kwargs
                )
            except PlaywrightError as exc:
                log.warning(
                    "Could not launch channel %r (%s); falling back to bundled "
                    "Chromium. Run `playwright install chromium` if this fails too.",
                    settings.browser_channel, exc.message.splitlines()[0],
                )
        if context is None:
            context = p.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(settings.nav_timeout_s * 1000)
            yield page
        finally:
            context.close()


def resolve(page: Page, cand: Candidate) -> Locator:
    kind = cand[0]
    if kind == "css":
        return page.locator(cand[1]).first
    if kind == "role":
        return page.get_by_role(cand[1], name=re.compile(cand[2], re.I)).first
    if kind == "text":
        return page.get_by_text(re.compile(cand[1], re.I)).first
    raise ValueError(f"Unknown candidate kind: {cand!r}")


def find_visible(page: Page, candidates: Sequence[Candidate]) -> Locator | None:
    """First candidate that is currently visible, or None."""
    for cand in candidates:
        try:
            loc = resolve(page, cand)
            if loc.is_visible():
                return loc
        except PlaywrightError:
            continue
    return None


def wait_visible(
    page: Page,
    candidates: Sequence[Candidate],
    timeout_s: float,
    description: str,
    poll_s: float = 0.5,
) -> Locator:
    """Poll all candidates until one is visible; raise TimeoutError otherwise."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        loc = find_visible(page, candidates)
        if loc is not None:
            return loc
        time.sleep(poll_s)
    raise TimeoutError(
        f"Timed out after {timeout_s:.0f}s waiting for {description}. "
        "Gemini's UI may have changed - see selectors.py."
    )
