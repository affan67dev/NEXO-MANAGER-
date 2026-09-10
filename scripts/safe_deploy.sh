#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Never stage private runtime files.
git check-ignore -q .env 2>/dev/null || true

# Refuse obvious secret material in tracked/staged changes.
if git diff --cached --binary | grep -Eiq '(TELEGRAM_BOT_TOKEN|api[_-]?key[[:space:]]*[:=]|bearer[[:space:]]+[A-Za-z0-9._~-]{12,}|-----BEGIN.*PRIVATE KEY)'; then
  echo 'ERROR: possible secret detected in staged changes. Aborting.' >&2
  exit 1
fi

python -m compileall -q telegram_llama.py app_router.py core services

git diff --check
git status --short

echo 'Review the status above. Commit/push manually with:'
echo '  git add -A && git commit -m "Secure NEXO runtime" && git push origin main'
