#!/usr/bin/env bash
set -euo pipefail

# Server-side Supertonic F3 worker.
# Run from a persistent clone of kanuli/daily-brief-newspaper-japanese.
# The server must already have Python 3.11+, ffmpeg, git credentials with push
# access, and the repository's Python requirements installed.

BRANCH="${BRANCH:-main}"

cd "$(dirname "$0")/.."

git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

python scripts/validate_content_integrity.py
python scripts/generate_supertonic_f3.py
python scripts/validate_content_integrity.py
python scripts/validate_site.py

git config user.name "daily-brief-japanese-audio-server"
git config user.email "actions@users.noreply.github.com"
git add audio data

if git diff --cached --quiet; then
  echo "SERVER_F3_NO_CHANGE"
  exit 0
fi

git commit -m "Supertonic F3音声をサーバー生成"

for attempt in 1 2 3 4 5; do
  git fetch origin "$BRANCH"
  if ! git rebase "origin/$BRANCH"; then
    git rebase --abort || true
    echo "Server audio became stale while newer news was published; retry on next server cycle."
    exit 0
  fi

  if git push origin "HEAD:$BRANCH"; then
    echo "SERVER_F3_PUSH_OK"
    exit 0
  fi

  sleep $((attempt * 2))
done

echo "SERVER_F3_PUSH_RETRIES_EXHAUSTED" >&2
exit 1
