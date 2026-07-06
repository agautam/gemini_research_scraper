"""Browser lifecycle: a persistent Chrome profile so the Google login
survives between runs, plus locator helpers for the candidate-selector
scheme defined in selectors.py."""

from __future__ import annotations

import logging
import os
import re
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, sync_playwright

from .config import Settings
from .selectors import Candidate

log = logging.getLogger(__name__)


class ProfileInUseError(RuntimeError):
    """The browser profile is held by a live process (a job is running)."""


def _handle_profile_lock(profile_dir: Path) -> None:
    """Chrome leaves a SingletonLock symlink ("<hostname>-<pid>") in the
    profile. After an ungraceful shutdown - e.g. the container was recreated
    mid-run, giving it a new hostname - the lock is stale and Chrome refuses
    to start, claiming the profile is in use "on another computer". Clear it
    when the owner is provably gone; fail clearly when it's provably alive."""
    lock = profile_dir / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return  # no lock (or not a platform that uses one, e.g. Windows)
    host, _, pid_s = target.rpartition("-")
    stale = True
    if host == socket.gethostname():
        try:
            os.kill(int(pid_s), 0)
            stale = False  # same host and the process exists
        except (ProcessLookupError, ValueError):
            stale = True
        except PermissionError:
            stale = False  # exists, owned by someone else
    if not stale:
        raise ProfileInUseError(
            f"The browser profile is in use by process {pid_s} - another "
            "research/login/extract is running right now. Wait for it to "
            "finish (or stop it) and retry."
        )
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (profile_dir / name).unlink(missing_ok=True)
        except OSError:
            pass
    log.info("Removed stale browser profile lock (was: %s).", target)


@contextmanager
def gemini_page(settings: Settings) -> Iterator[Page]:
    """Launch a persistent-profile browser and yield a page. The profile can
    only be attached to one browser at a time, so callers must not overlap."""
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    _handle_profile_lock(settings.profile_dir)
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


# Cookies Google only sets for an authenticated session. Checking these is
# locale- and DOM-independent, unlike looking for a "Sign in" button — the
# signed-out page can transiently render an app shell that fools DOM checks.
_AUTH_COOKIE_NAMES = {"__Secure-1PSID", "__Secure-3PSID", "SAPISID", "SID"}


def has_google_session(page: Page) -> bool:
    cookies = page.context.cookies("https://gemini.google.com")
    return bool(_AUTH_COOKIE_NAMES & {c["name"] for c in cookies})


def _resolve_all(page: Page, cand: Candidate) -> Locator:
    kind = cand[0]
    if kind == "css":
        return page.locator(cand[1])
    if kind == "role":
        return page.get_by_role(cand[1], name=re.compile(cand[2], re.I))
    if kind == "text":
        return page.get_by_text(re.compile(cand[1], re.I))
    raise ValueError(f"Unknown candidate kind: {cand!r}")


def resolve(page: Page, cand: Candidate) -> Locator:
    return _resolve_all(page, cand).first


def find_visible(page: Page, candidates: Sequence[Candidate]) -> Locator | None:
    """First VISIBLE match across all candidates, or None. Checks every match
    of each candidate, not just the first - Gemini keeps hidden duplicates of
    some controls in the DOM (responsive layouts, stale stream renders)."""
    for cand in candidates:
        try:
            loc = _resolve_all(page, cand)
            for i in range(min(loc.count(), 8)):
                nth = loc.nth(i)
                if nth.is_visible():
                    return nth
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
