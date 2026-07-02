#!/usr/bin/env bash
# One-shot bring-up for reviewers: install → migrate → run (API + client).
# The support-triage graph seeds itself on API startup, so no seed step is needed.
set -euo pipefail
cd "$(dirname "$0")"

# 1. Environment — the agent nodes need a Groq key.
if [ ! -f api/.env ]; then
  cp api/.env.example api/.env
  echo "⚠  Created api/.env from the template — add your GROQ_API_KEY before running,"
  echo "   then re-run ./start.sh. (The agent nodes make real Groq calls.)"
  exit 1
fi
if ! grep -q '^GROQ_API_KEY=gsk' api/.env; then
  echo "⚠  api/.env has no GROQ_API_KEY set (expected GROQ_API_KEY=gsk_...)."
  echo "   Add it, then re-run ./start.sh."
  exit 1
fi

# 2. Dependencies.
echo "→ Installing Python deps (uv sync)…"
uv sync --directory api
echo "→ Installing frontend deps (pnpm install)…"
pnpm install

# 3. Database schema. (Graph seeding runs automatically on API startup.)
echo "→ Applying migrations…"
uv --directory api run alembic upgrade head

# 4. Run both. API :8000  ·  client :3000. Ctrl-C stops both.
echo "→ Starting API (:8000) + client (:3000)…  seed runs on API startup."
pnpm dev
