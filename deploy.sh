#!/usr/bin/env bash
# Deploy gemini-research-scraper: pull the latest code, rebuild the image,
# and restart the service via docker compose.
#
# Usage: ./deploy.sh [branch]
#   branch  Optional branch to deploy (defaults to the currently checked-out one).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# Prefer the `docker compose` plugin, fall back to legacy docker-compose.
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "ERROR: neither 'docker compose' nor 'docker-compose' is available." >&2
    exit 1
fi

BRANCH="${1:-}"
if [[ -n "$BRANCH" ]]; then
    echo "==> Checking out branch '$BRANCH'"
    git checkout "$BRANCH"
fi

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Building image"
"${COMPOSE[@]}" build --pull

echo "==> Starting service"
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> Deployed $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD))"
"${COMPOSE[@]}" ps
