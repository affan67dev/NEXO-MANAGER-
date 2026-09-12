# NEXO Safe Pull Deployment

NEXO uses a local pull-based deployment on the Termux tablet.

Flow:

`GitHub main push -> NEXO CI PASS -> tablet SHA polling (30 min) -> immutable release worktree -> local tests -> tracked-file runtime sync -> restart nexo-backend + nexo-llama -> health check -> fast-forward main`

## One-time activation

From the tablet, after pulling this repository version:

```bash
bash ~/NEXO/scripts/bootstrap_nexo_deploy.sh
```

The bootstrap verifies the Termux environment, repository identity, required PM2 processes, existing tablet startup scripts, and a clean tracked working tree. It records the current commit as the initial known-good release and installs one cron entry at `*/30 * * * *`.

## Safety model

- No `git reset --hard`.
- No `git clean`.
- No forced checkout.
- No force push.
- Local tracked changes block automatic deployment.
- `.env`, SQLite files, GGUF models, logs, secrets and credentials remain outside the release file set.
- Release candidates are immutable detached Git worktrees under `~/.nexo/deploy/releases/`.
- Only tracked files are synchronized into the runtime checkout.
- Git history advances only with `git merge --ff-only` after runtime health succeeds.
- A failed deployment gets one rollback attempt to the previous known-good release.
- An interrupted transaction is recovered on the next poll before a new deployment is attempted.
- Only `nexo-backend` and `nexo-llama` are restarted. `omnix-backend` is never referenced by the deployment scripts.

## CI gate

The poller checks the GitHub Actions workflow named `NEXO CI` for the exact target SHA. A deployment is not attempted until that workflow has completed successfully.

## Dependency policy

Python dependencies are not reinstalled when dependency manifests are unchanged. If a dependency manifest changes, the deployment uses the repository's `requirements-nexo.txt` before restarting NEXO.

## Logs and state

Deployment state and logs live under:

`~/.nexo/deploy/`

The repository itself is not used to store runtime secrets or model/database state.

## Important runtime boundary

The tablet already owns the PM2 runtime configuration and the startup scripts:

- `~/NEXO/start_llama_tablet.sh`
- `~/NEXO/start_nexo_tablet.sh`

The deployment system deliberately does not rewrite those scripts or create a second PM2 configuration. It updates the tracked application files in place, then restarts the existing NEXO process names.
