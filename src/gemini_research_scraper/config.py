"""Runtime settings. Every value can be overridden via GRS_* environment
variables or CLI flags; environment parsing lives here so the rest of the
code only ever sees a fully-populated Settings object."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PROFILE_DIR = Path.home() / ".gemini-research-scraper" / "browser-profile"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass
class Settings:
    # Where the persistent (logged-in) Chrome profile lives. Log in once with
    # `gemini-research login`; every later run reuses the same profile.
    profile_dir: Path = DEFAULT_PROFILE_DIR

    # Headful by default: Google sign-in and Gemini itself are far less likely
    # to be blocked when a real, visible Chrome window is used.
    headless: bool = False

    # "chrome" uses the system Chrome install (recommended). Set to "" / None
    # to use Playwright's bundled Chromium (`playwright install chromium`).
    browser_channel: str | None = "chrome"

    # Required when Chromium runs as root inside a container (also enables
    # --disable-dev-shm-usage to survive Docker's small default /dev/shm).
    no_sandbox: bool = False

    base_url: str = "https://gemini.google.com/app"

    nav_timeout_s: int = 60
    # Time allowed for Gemini to produce the research plan after the query.
    plan_timeout_s: int = 300
    # Deep Research runs are long; 45 minutes is a safe upper bound.
    research_timeout_s: int = 2700
    poll_interval_s: int = 5

    output_dir: Path = field(default_factory=lambda: Path("research_output"))

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        if v := os.environ.get("GRS_PROFILE_DIR"):
            s.profile_dir = Path(v)
        s.headless = _env_bool("GRS_HEADLESS", s.headless)
        if (v := os.environ.get("GRS_BROWSER_CHANNEL")) is not None:
            s.browser_channel = v or None
        s.no_sandbox = _env_bool("GRS_NO_SANDBOX", s.no_sandbox)
        if v := os.environ.get("GRS_BASE_URL"):
            s.base_url = v
        s.nav_timeout_s = _env_int("GRS_NAV_TIMEOUT_S", s.nav_timeout_s)
        s.plan_timeout_s = _env_int("GRS_PLAN_TIMEOUT_S", s.plan_timeout_s)
        s.research_timeout_s = _env_int("GRS_RESEARCH_TIMEOUT_S", s.research_timeout_s)
        s.poll_interval_s = _env_int("GRS_POLL_INTERVAL_S", s.poll_interval_s)
        if v := os.environ.get("GRS_OUTPUT_DIR"):
            s.output_dir = Path(v)
        return s
