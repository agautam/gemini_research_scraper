# Gemini Deep Research scraper for Unraid / Docker.
#
# The browser runs HEADFUL on a virtual display (Xvfb) because Google is far
# less hostile to a real, visible Chrome — and you need to see the window
# anyway for the one-time Google sign-in. The display is exposed over noVNC
# on port 6080, so login and progress-watching happen from any browser tab.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DISPLAY=:99 \
    # Container defaults: bundled Chromium, headful on Xvfb, root sandbox off,
    # state on the /config and /output volumes.
    GRS_BROWSER_CHANNEL="" \
    GRS_HEADLESS=false \
    GRS_NO_SANDBOX=true \
    GRS_PROFILE_DIR=/config/browser-profile \
    GRS_OUTPUT_DIR=/output

RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc novnc websockify tini fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/config", "/output"]
EXPOSE 8000 6080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

ENTRYPOINT ["tini", "--", "/entrypoint.sh"]
CMD ["gemini-research", "serve", "--host", "0.0.0.0", "--port", "8000"]
