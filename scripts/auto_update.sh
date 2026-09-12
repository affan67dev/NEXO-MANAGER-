#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

REPO_DIR="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
STATE_DIR="${HOME}/.nexo/deploy"
RELEASE_DIR="${STATE_DIR}/releases"
LOG_FILE="${STATE_DIR}/auto_update.log"
LOCK_DIR="${STATE_DIR}/lock"
REMOTE="origin"
BRANCH="main"
REPO_SLUG="affan67dev/NEXO-MANAGER-"
CI_WORKFLOW="NEXO CI"
HEALTH_URL="http://127.0.0.1:8080/health"
HEALTH_ATTEMPTS=6
HEALTH_DELAY=5

mkdir -p "$STATE_DIR" "$RELEASE_DIR"
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }
fail() { log "ERROR: $*"; exit 1; }
if ! mkdir "$LOCK_DIR" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
cd "$REPO_DIR"
[[ "$(git config --get remote.origin.url || true)" == *"affan67dev/NEXO-MANAGER-"* ]] || fail "unexpected origin repository"
[[ "$(git branch --show-current)" == "$BRANCH" ]] || fail "repository is not on main"
state() { cat "${STATE_DIR}/$1" 2>/dev/null || true; }
write_state() { printf '%s\n' "$2" > "${STATE_DIR}/$1"; }

pm2_ok() {
  command -v pm2 >/dev/null 2>&1 || return 1
  pm2 describe nexo-backend >/dev/null 2>&1 || return 1
  pm2 describe nexo-llama >/dev/null 2>&1 || return 1
  local statuses
  statuses="$(pm2 jlist 2>/dev/null | python -c 'import json,sys; d=json.load(sys.stdin); names={p.get("name"):p.get("pm2_env",{}).get("status") for p in d}; print(names.get("nexo-backend",""),names.get("nexo-llama",""))' 2>/dev/null || true)"
  [[ "$statuses" == "online online" ]]
}
restart_nexo() { pm2 describe nexo-backend >/dev/null 2>&1 && pm2 describe nexo-llama >/dev/null 2>&1 && pm2 restart nexo-backend nexo-llama --update-env >/dev/null; }
health_ok() {
  local attempt status
  for ((attempt=1; attempt<=HEALTH_ATTEMPTS; attempt++)); do
    status="$(curl --silent --show-error --max-time 10 --output /dev/null --write-out '%{http_code}' "$HEALTH_URL" 2>/dev/null || printf '000')"
    if [[ "$status" == "200" ]] && pm2_ok; then return 0; fi
    [[ "$attempt" -lt "$HEALTH_ATTEMPTS" ]] && sleep "$HEALTH_DELAY"
  done
  return 1
}
ci_passed() {
  local sha="$1" json
  json="$(curl --fail --silent --show-error --max-time 20 -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' "https://api.github.com/repos/${REPO_SLUG}/actions/runs?head_sha=${sha}&branch=${BRANCH}&per_page=20")" || return 1
  JSON_DATA="$json" python - "$sha" "$CI_WORKFLOW" <<'PY'
import json,os,sys
sha,name=sys.argv[1:3]
runs=json.loads(os.environ["JSON_DATA"]).get("workflow_runs",[])
for run in sorted(runs,key=lambda r:r.get("run_number",0),reverse=True):
    if run.get("name")==name and run.get("head_sha")==sha:
        sys.exit(0 if run.get("status")=="completed" and run.get("conclusion")=="success" else 1)
sys.exit(1)
PY
}
remote_sha() { git ls-remote --heads "$REMOTE" "refs/heads/$BRANCH" | awk '{print $1}'; }
make_release() {
  local sha="$1" path="${RELEASE_DIR}/${sha}"
  if [[ -e "$path/.git" ]]; then [[ "$(git -C "$path" rev-parse HEAD 2>/dev/null)" == "$sha" ]] || return 1; printf '%s' "$path"; return 0; fi
  git worktree add --detach --quiet "$path" "$sha" || return 1
  printf '%s' "$path"
}
run_tests() { local release="$1"; (cd "$release" && python -m compileall -q . && python -m unittest discover -s tests -v); }
dep_changed() { git diff --name-only "$1" "$2" -- 'requirements*.txt' 'pyproject.toml' 'Pipfile' 'Pipfile.lock' 'poetry.lock' 'uv.lock' | grep -q .; }
install_dependencies_if_needed() {
  local old="$1" new="$2" release="$3"
  if dep_changed "$old" "$new"; then
    log "DEPENDENCIES: manifest changed; installing requirements-nexo.txt"
    [[ -f "$release/requirements-nexo.txt" ]] || fail "requirements-nexo.txt missing"
    python -m pip install -r "$release/requirements-nexo.txt" || fail "dependency installation failed"
  else log "DEPENDENCIES: unchanged; no reinstall"; fi
}
sync_release_to_runtime() {
  local release="$1"
  git -C "$release" ls-files -z | rsync -a --from0 --files-from=- "$release/" "$REPO_DIR/"
  comm -z -23 <(git ls-files -z | sort -z) <(git -C "$release" ls-files -z | sort -z) | while IFS= read -r -d '' f; do rm -f -- "$REPO_DIR/$f"; done
}
restore_release() { local release="$1" sha="$2"; sync_release_to_runtime "$release"; git read-tree -u "$sha"; }
recover_interrupted() {
  [[ -f "${STATE_DIR}/transaction" ]] || return 0
  local previous path
  previous="$(state previous_sha)"
  [[ -n "$previous" ]] || fail "transaction state is incomplete"
  path="$(make_release "$previous")" || fail "previous release unavailable"
  log "RECOVERY: restoring $previous"
  restore_release "$path" "$previous" || fail "recovery restore failed"
  restart_nexo || fail "recovery restart failed"
  sleep 10
  health_ok || fail "recovery health check failed"
  rm -f "${STATE_DIR}/transaction"
}
recover_interrupted
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { log "SKIP: local tracked changes detected"; exit 0; }
CURRENT_SHA="$(git rev-parse HEAD)" || fail "cannot read current SHA"
REMOTE_SHA="$(remote_sha)" || fail "cannot read remote SHA"
[[ -n "$REMOTE_SHA" ]] || fail "remote SHA empty"
[[ "$CURRENT_SHA" != "$REMOTE_SHA" ]] || exit 0
ci_passed "$REMOTE_SHA" || { log "WAIT: CI not PASS for $REMOTE_SHA"; exit 0; }
git fetch --quiet --no-tags "$REMOTE" "$BRANCH" || fail "git fetch failed"
git merge-base --is-ancestor "$CURRENT_SHA" "$REMOTE_SHA" || fail "remote main is not a fast-forward"
TARGET_RELEASE="$(make_release "$REMOTE_SHA")" || fail "cannot create target release"
run_tests "$TARGET_RELEASE" || fail "release tests failed"
install_dependencies_if_needed "$CURRENT_SHA" "$REMOTE_SHA" "$TARGET_RELEASE"
PREVIOUS_RELEASE="$(make_release "$CURRENT_SHA")" || fail "cannot create previous release"
write_state previous_sha "$CURRENT_SHA"
write_state target_sha "$REMOTE_SHA"
: > "${STATE_DIR}/transaction"
log "DEPLOY: $CURRENT_SHA -> $REMOTE_SHA"
restore_release "$TARGET_RELEASE" "$REMOTE_SHA" || fail "runtime staging failed"
if ! restart_nexo; then
  log "FAILURE: NEXO restart failed; one rollback attempt"
  restore_release "$PREVIOUS_RELEASE" "$CURRENT_SHA" || fail "rollback restore failed"
  restart_nexo || fail "rollback restart failed"
  sleep 10
  health_ok || fail "rollback health failed"
  rm -f "${STATE_DIR}/transaction"
  exit 1
fi
sleep 10
if health_ok; then
  git read-tree -u "$REMOTE_SHA"
  if git merge --ff-only "$REMOTE_SHA" >/dev/null; then
    write_state known_good_sha "$REMOTE_SHA"
    write_state deployed_sha "$REMOTE_SHA"
    rm -f "${STATE_DIR}/transaction"
    log "SUCCESS: deployed $REMOTE_SHA"
    exit 0
  fi
fi
log "FAILURE: health or finalization failed; one rollback attempt"
restore_release "$PREVIOUS_RELEASE" "$CURRENT_SHA" || fail "rollback restore failed"
restart_nexo || fail "rollback restart failed"
sleep 10
health_ok || fail "rollback health failed"
rm -f "${STATE_DIR}/transaction"
log "ROLLBACK SUCCESS: restored $CURRENT_SHA"
exit 1
