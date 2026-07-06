# gemini-research-scraper

Runs **Gemini Deep Research** on your behalf through a real browser at
[gemini.google.com](https://gemini.google.com): enables Deep Research mode,
submits your query, approves the generated research plan, waits for the
(long-running) research to finish, scrapes the report, and saves it as a
Markdown/HTML document. Available as a CLI and as a small HTTP API.

Built with Python + [Playwright](https://playwright.dev/python/) using a
**persistent Chrome profile** — you sign in to Google once, and every later
run reuses that session.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

By default the tool drives your **system Chrome** (`browser_channel = "chrome"`).
If you don't have Chrome installed, either install it or fetch Playwright's
bundled Chromium and point the tool at it:

```powershell
playwright install chromium
$env:GRS_BROWSER_CHANNEL = ""   # empty -> use bundled Chromium
```

## 1. Sign in once

```powershell
gemini-research login
```

A Chrome window opens on gemini.google.com. Sign in to your Google account;
the tool detects the signed-in state and stores the session in
`~/.gemini-research-scraper/browser-profile`.

## 2. Run a research

```powershell
gemini-research run "What are the current approaches to solid-state battery manufacturing at scale?"
```

What happens:

1. Opens Gemini with your saved session (a visible Chrome window by default).
2. Enables **Deep Research** (composer chip or Tools menu, whichever the UI shows).
3. Submits the query and waits for Gemini's research plan.
4. Clicks **Start research** to approve the plan.
5. Polls until the research completes (default cap: 45 min).
6. Scrapes the report and writes `research_output/<timestamp>-<title>.md`.

Useful flags: `-o report.md` (explicit output path), `--format md,html`,
`--timeout-min 60`, `--headless`, `-v` for debug logging.

## 3. Or run it as a service

```powershell
gemini-research serve --port 8000
```

```
POST /research                          {"query": "..."}   -> 202 {"job_id": "..."}
GET  /research/{job_id}                                    -> status / metadata
GET  /research/{job_id}/document?format=md|html            -> the report document
```

Jobs are executed **sequentially** — one browser profile supports one
research at a time; additional requests wait in a queue. Job state is held
in memory (restarts clear it); the interactive docs live at `/docs`.

## Running on Unraid (Docker)

The container runs the HTTP API plus a virtual display (Xvfb) with a built-in
**noVNC** web viewer, so the one-time Google sign-in — and watching a research
run live — happens right in your browser. No GPU or display needed on the host.

### Build the image

There is no published registry image; build it on the Unraid box (Unraid
terminal, or anywhere with Docker and copy it over):

```bash
git clone <this-repo> && cd gemini_research_scraper
docker build -t gemini-research-scraper:latest .
```

### Option A: docker-compose

Adjust the volume paths in [docker-compose.yml](docker-compose.yml) (on Unraid
typically `/mnt/user/appdata/gemini-research-scraper` for `/config` and a
share like `/mnt/user/documents/research` for `/output`), then:

```bash
docker compose up -d
```

### Option B: Unraid Docker UI template

Copy [docker/unraid-template.xml](docker/unraid-template.xml) to
`/boot/config/plugins/dockerMan/templates-user/` on the Unraid flash drive,
then add the container via **Docker → Add Container** and pick the template.

### Ports and volumes

| | |
|---|---|
| `8000` | HTTP API — interactive docs at `http://<unraid-ip>:8000/docs` |
| `6080` | noVNC browser viewer — `http://<unraid-ip>:6080/vnc.html` |
| `/config` | Persistent browser profile (your Google session) |
| `/output` | Finished reports; every completed job writes `.md` + `.html` here |

### One-time Google sign-in

1. Open the noVNC viewer: `http://<unraid-ip>:6080/vnc.html` and connect.
2. In the Unraid terminal run:
   ```bash
   docker exec -it gemini-research-scraper gemini-research login
   ```
3. A Chrome window appears in the noVNC tab — sign in to Google there.
   The session persists in `/config` across container restarts.

Don't run `login` while a research job is in flight (one browser profile at a
time). After signing in, drive everything over the API:

```bash
curl -X POST http://<unraid-ip>:8000/research \
     -H "Content-Type: application/json" \
     -d '{"query": "State of solid-state battery manufacturing at scale"}'
# -> {"job_id": "...", "status": "queued", ...}

curl http://<unraid-ip>:8000/research/<job_id>            # status
curl http://<unraid-ip>:8000/research/<job_id>/document   # the report (md)
```

Finished reports also land in the `/output` share automatically.

> The API has no authentication — keep ports 8000/6080 on your LAN (don't
> expose them through a reverse proxy to the internet as-is).

## Configuration

Environment variables (all optional; CLI flags override them):

| Variable | Default | Meaning |
|---|---|---|
| `GRS_PROFILE_DIR` | `~/.gemini-research-scraper/browser-profile` | Persistent browser profile |
| `GRS_HEADLESS` | `false` | Headless browser (headful is more reliable with Google) |
| `GRS_BROWSER_CHANNEL` | `chrome` | Chrome channel; empty string = bundled Chromium (container default) |
| `GRS_NO_SANDBOX` | `false` (`true` in container) | Chromium `--no-sandbox` + `--disable-dev-shm-usage`, needed as root in Docker |
| `GRS_PLAN_TIMEOUT_S` | `300` | Max wait for the research plan |
| `GRS_RESEARCH_TIMEOUT_S` | `2700` | Max wait for the research itself |
| `GRS_OUTPUT_DIR` | `./research_output` | Where CLI reports are written |

## When Gemini's UI changes

All DOM knowledge is isolated in
[`src/gemini_research_scraper/selectors.py`](src/gemini_research_scraper/selectors.py).
Each UI element is a prioritized list of selector candidates (CSS, ARIA role,
or visible text); the automation uses the first visible match. If a step
starts timing out, run with `-v`, inspect the live page, and prepend a new
candidate — no other code should need to change.

## Notes and caveats

- The tool automates the consumer Gemini web app under **your own account**,
  which may sit in tension with Google's Terms of Service. Use for personal
  research at human-like volumes; there is no official API for Deep Research.
- Google sign-in inside `login` must be completed by a human (2FA, CAPTCHA).
  Headless mode works for later runs but is more likely to be challenged.
- Deep Research runs commonly take 5–25 minutes; timeouts are configurable.
- Only one run at a time per profile: the CLI and the server must not use the
  same profile concurrently, and the server serializes its own jobs.
