# NEXO Safe Deployment

The supported runtime is the hosted OpenRouter architecture.

```text
GitHub change
  → NEXO CI
  → human review
  → immutable release
  → deploy hosted ALEX runtime
  → health verification
```

## Runtime boundary

Deployment manages the ALEX/NEXO application service only. It must not start, discover, download, or depend on local model servers or model files.

The release file set excludes:

- `.env` and `.nexo.env`;
- SQLite runtime databases where deployment policy excludes them;
- model files;
- logs;
- credentials and secrets.

## Safety gates

- No force push.
- No automatic merge.
- No deployment from a dirty tracked worktree.
- CI must pass before release promotion.
- Runtime health must be verified after deployment.
- Failed health checks must not be reported as successful deployment.
- Provider/API credentials remain server-side.

## Portfolio API

The public Portfolio API is a separate FastAPI entrypoint:

```text
HTTPS Portfolio Website
        ↓
portfolio_api.py
        ↓
public_portfolio RequestContext
        ↓
Portfolio policy + public knowledge
        ↓
ExecutivePlanner → LLMRouter → OpenRouterProvider
```

Production configuration must define an exact HTTPS CORS origin and a server-side Portfolio session secret.

## Public knowledge

Public GitHub README ingestion is an allowlisted knowledge-refresh operation. It is not a live activity feed.

Only explicitly public repositories are eligible, and the resulting documents are stored under the `public_portfolio` scope.

## Verification

A release is not complete until:

1. CI has an actual successful result.
2. Syntax/import checks pass.
3. Complete unit tests pass.
4. Runtime health is verified.
5. The hosted provider is reachable using server-side credentials.
6. No local-model dependency has been introduced.

