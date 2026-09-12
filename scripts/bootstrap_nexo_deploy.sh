#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

# One-time NEXO Termux deployment bootstrap.
# It configures a lightweight 30-minute poller and records the current runtime
# as the initial known-good release. It never manages omnix-backend.

REPO_DIR="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
STATE_DIR="${HOME}/.nexo/deploy"
CRON_TAG="# NEXO_SAFE_DEPLOY_30M"

say() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ -n "${PREFIX:-}" && -d "$PREFIX" ]] || fail "Termux environment not detected"
command -v git >/dev/null 2>&1 || fail "git is required"
command -v python >/dev/null 2>&1 || fail "python is required"
command -v pm2 >/dev/null 2>&1 || fail "pm2 is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v rsync >/dev/null 2>&1 || fail "rsync is required"
command -v crontab >/dev/null 2>&1 || fail "cronie/crontab is required"

[[ -d "$REPO_DIR/.git" ]] || fail "NEXO repository root not found"
[[ "$(git -C "$REPO_DIR" config --get remote.origin.url || true)" == *"affan67dev/NEXO-MANAGER-"* ]] || fail "unexpected Git remote"
[[ -f "$REPO_DIR/scripts/auto_update.sh" ]] || fail "auto_update.sh missing"
[[ -f "$HOME/NEXO/start_llama_tablet.sh" ]] || fail "~/NEXO/start_llama_tablet.sh missing"
[[ -f "$HOME/NEXO/start_nexo_tablet.sh" ]] || fail "~/NEXO/start_nexo_tablet.sh missing"

pm2 describe nexo-backend >/dev/null 2>&1 || fail "PM2 process nexo-backend not found"
pm2 describe nexo-llama >/dev/null 2>&1 || fail "PM2 process nexo-llama not found"

# Refuse to overwrite tracked local work.
[[ -z "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]] || fail "tracked local changes detected"

bash -n "$REPO_DIR/scripts/auto_update.sh"
mkdir -p "$STATE_DIR/releases"
CURRENT_SHA="$(git -C "$REPO_DIR" rev-parse HEAD)"
RELEASE="$STATE_DIR/releases/$CURRENT_SHA"

if [[ ! -e "$RELEASE/.git" ]]; then
  git -C "$REPO_DIR" worktree add --detach --quiet "$RELEASE" "$CURRENT_SHA" || fail "initial release worktree creation failed"
fi

printf '%s\n' "$CURRENT_SHA" > "$STATE_DIR/known_good_sha"
printf '%s\n' "$CURRENT_SHA" > "$STATE_DIR/deployed_sha"
rm -f "$STATE_DIR/transaction"

# Keep exactly one scheduler entry. The scheduler only performs SHA metadata
# polling and exits immediately when main has not changed.
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
(crontab -l 2>/dev/null || true) | grep -vF "$CRON_TAG" > "$TMP" || true
printf '*/30 * * * * %q >> %q 2>&1 %s\n' "$REPO_DIR/scripts/auto_update.sh" "$STATE_DIR/cron.log" "$CRON_TAG" >> "$TMP"
crontab "$TMP"

if ! pgrep -x crond >/dev/null 2>&1; then
  nohup crond >/dev/null 2>&1 &
fi

chmod +x "$REPO_DIR/scripts/auto_update.sh"

say "NEXO safe deployment bootstrap: PASS"
say "Known-good SHA: $CURRENT_SHA"
say "Poll interval: 30 minutes"
say "Managed PM2 processes: nexo-backend, nexo-llama"
say "Runtime data remains outside Git release tracking"
say "No OMNIX process is managed"
say "Scheduler installed; no further activation command is required."
