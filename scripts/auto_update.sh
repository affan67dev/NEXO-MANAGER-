#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

# NEXO local pull-based deployment for Termux + cron.
# This script intentionally performs no remote SSH/deployment actions.

REPO_DIR="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
LOG_DIR="${HOME}/.nexo"
LOG_FILE="${LOG_DIR}/auto_update.log"
LOCK_DIR="${LOG_DIR}/auto_update.lock"
BRANCH="main"
HEALTH_URL="http://127.0.0.1:8080/health"
HEALTH_ATTEMPTS=6
HEALTH_DELAY=5

mkdir -p "$LOG_DIR"

# Prevent overlapping cron executions.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

fail() {
    log "ERROR: $*"
    exit 1
}

cd "$REPO_DIR"

# Refuse to pull over local tracked changes. Runtime files such as .env and
# SQLite are expected to be ignored by Git and therefore remain untouched.
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    log "SKIP: local tracked changes detected; refusing automatic deployment"
    exit 0
fi

CURRENT_COMMIT="$(git rev-parse HEAD)" || fail "cannot read current commit"

# Fetch metadata only; no working-tree changes occur here.
git fetch --quiet origin "$BRANCH" || fail "git fetch failed"
REMOTE_COMMIT="$(git rev-parse "origin/$BRANCH")" || fail "cannot resolve origin/$BRANCH"

# No update: exit silently as requested.
if [[ "$CURRENT_COMMIT" == "$REMOTE_COMMIT" ]]; then
    exit 0
fi

PREVIOUS_COMMIT="$CURRENT_COMMIT"
log "UPDATE: $PREVIOUS_COMMIT -> $REMOTE_COMMIT"

# Fast-forward only: never create an implicit merge commit or overwrite local history.
git pull --ff-only origin "$BRANCH" || fail "git pull failed; deployment not started"

restart_services() {
    command -v pm2 >/dev/null 2>&1 || return 1

    # Require both expected NEXO processes to already exist. This prevents
    # accidental creation/duplication of processes during auto-deployment.
    pm2 describe nexo-backend >/dev/null 2>&1 || return 1
    pm2 describe nexo-llama >/dev/null 2>&1 || return 1

    pm2 restart nexo-backend nexo-llama --update-env >/dev/null
    pm2 save >/dev/null 2>&1 || true
}

health_check() {
    local attempt status body

    for ((attempt=1; attempt<=HEALTH_ATTEMPTS; attempt++)); do
        body="$(mktemp "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/nexo-health.XXXXXX")"
        status="$(curl --silent --show-error --max-time 10 --output "$body" --write-out '%{http_code}' "$HEALTH_URL" 2>/dev/null || printf '000')"

        if [[ "$status" == "200" ]] && [[ -s "$body" ]]; then
            rm -f "$body"
            return 0
        fi

        rm -f "$body"
        [[ "$attempt" -lt "$HEALTH_ATTEMPTS" ]] && sleep "$HEALTH_DELAY"
    done

    return 1
}

pm2_healthy() {
    local backend_status llama_status
    backend_status="$(pm2 jlist 2>/dev/null | python -c 'import json,sys; d=json.load(sys.stdin); x=next((p for p in d if p.get("name")=="nexo-backend"),None); print((x or {}).get("pm2_env",{}).get("status",""))' 2>/dev/null || true)"
    llama_status="$(pm2 jlist 2>/dev/null | python -c 'import json,sys; d=json.load(sys.stdin); x=next((p for p in d if p.get("name")=="nexo-llama"),None); print((x or {}).get("pm2_env",{}).get("status",""))' 2>/dev/null || true)"
    [[ "$backend_status" == "online" && "$llama_status" == "online" ]]
}

verify_runtime() {
    pm2_healthy && health_check
}

# Deployment.
if ! restart_services; then
    log "FAILURE: required PM2 services could not be restarted"
else
    sleep 15
    if verify_runtime; then
        log "Success: deployed $REMOTE_COMMIT; PM2 and HTTP health check passed"
        exit 0
    fi
    log "FAILURE: post-deployment health verification failed"
fi

# Genuine rollback: restore the exact previously running Git revision.
log "ROLLBACK: restoring $PREVIOUS_COMMIT"
if ! git reset --hard "$PREVIOUS_COMMIT" >/dev/null 2>&1; then
    log "CRITICAL: git rollback failed"
    exit 1
fi

if ! restart_services; then
    log "CRITICAL: PM2 restart failed during rollback"
    exit 1
fi

sleep 15
if verify_runtime; then
    log "ROLLBACK SUCCESS: restored $PREVIOUS_COMMIT and runtime is healthy"
    exit 1
fi

log "CRITICAL: rollback completed at Git level but runtime health verification failed"
exit 1
