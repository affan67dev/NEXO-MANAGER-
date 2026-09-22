# NEXO Manager / ALEX

NEXO Manager is the orchestration system behind **ALEX**, the user-facing AI identity.

The current runtime is **hosted-model based**:

```text
Request
  ↓
RequestContext / deterministic policy
  ↓
NexoManager / ExecutivePlanner
  ↓
LLMRouter
  ↓
OpenRouterProvider
  ↓
configured hosted model
  ↓
verified tool execution where authorized
```

ALEX does not receive authority from model output. Authentication, authorization, scope, tool permissions and public/private boundaries are enforced outside the LLM.

## Current architecture

- **ALEX** — user-facing identity.
- **NexoManager** — orchestration/runtime coordination.
- **ExecutivePlanner** — request planning and bounded tool orchestration.
- **LLMRouter** — provider/model routing.
- **OpenRouterProvider** — hosted OpenAI-compatible model transport.
- **RequestContext** — deterministic channel, actor and scope identity.
- **Telegram runtime** — separate public/admin bot boundaries.
- **Portfolio AI API** — public-only HTTPS API using `portfolio_web / visitor / public_portfolio`.
- **Public knowledge** — explicitly allowlisted public GitHub README ingestion.
- **SQLite/Supabase integrations** — used only through their authorized server-side paths.
- **Android/voice capabilities** — allowlisted and independently verified; they are not exposed to public Portfolio visitors.

## Hosted LLM runtime

The production LLM path requires:

- `LLM_PROVIDER=openrouter`
- `LLM_API_KEY` (server-side only)
- `LLM_MODEL`
- `LLM_BASE_URL=https://openrouter.ai/api/v1`

Optional fallback model IDs can be configured with `LLM_FALLBACK_MODELS`.

The application does **not** require or depend on:

- a local `llama-server`
- GGUF model files
- `NEXO_MODEL_PATH`
- `LLAMA_SERVER`
- `127.0.0.1:8080`
- local model discovery
- a local-model fallback

Hosted model failures are bounded by the provider retry policy and are never converted into fabricated successful results.

## Telegram isolation

Telegram identity is server-derived.

The public Telegram bot cannot become an administrator because a user writes a message such as "I am admin". The configured admin bot requires the server-side administrator Telegram user ID.

Public Telegram requests receive public-client context. Administrator requests receive owner/admin context only after deterministic authorization.

Privileged tool schemas are filtered before the model can request them, and execution authorization remains enforced independently.

## Portfolio AI

The public API is implemented in `portfolio_api.py`.

The intended production boundary is:

```text
Portfolio Website
    ↓ HTTPS
ALEX Portfolio API
    ↓
RequestContext.portfolio(...)
    ↓
Portfolio policy
    ↓
public_portfolio knowledge retrieval
    ↓
ExecutivePlanner / hosted OpenRouter model
```

The public context is always:

```text
channel    = portfolio_web
actor_type = visitor
scope      = public_portfolio
owner      = false
actor_id   = none
```

The API uses:

- signed HttpOnly visitor sessions;
- Secure/SameSite cookie settings for HTTPS deployment;
- an explicit CORS allowlist;
- public-session rate limiting;
- visitor-specific history;
- deterministic public/private policy checks;
- no browser-visible provider credentials.

Required server-side Portfolio settings are documented in `.nexo.env.example`:

- `NEXO_PORTFOLIO_ALLOWED_ORIGINS`
- `NEXO_PORTFOLIO_SESSION_SECRET`
- `NEXO_PORTFOLIO_COOKIE_SECURE`
- `NEXO_PORTFOLIO_RATE_LIMIT`
- `NEXO_PORTFOLIO_RATE_WINDOW_SECONDS`

The Portfolio browser must never receive `LLM_API_KEY`, Supabase service-role credentials, Telegram bot tokens, or `.nexo.env`.

## Public knowledge

Only explicitly allowlisted public GitHub repositories are ingested.

The default public knowledge list is:

- `affan67dev/NEXO-MANAGER-`
- `affan67dev/OMNIX`
- `affan67dev/PicSyncApp`
- `affan67dev/ajentic-AI-model`

The refresh process reads public README content, removes configured sensitive sections/lines, stores it as `public_portfolio` knowledge, and versions the source by its GitHub README SHA.

README ingestion is **not** real-time GitHub activity tracking.

If live public activity is required later, it must be implemented as a separate controlled public-activity ingestion path.

## Security boundary

Public Portfolio visitors cannot access:

- private Telegram conversations;
- administrator memory;
- credentials or API keys;
- private repositories;
- filesystem or shell;
- arbitrary code execution;
- privileged tools;
- scheduler controls;
- OpenHands execution;
- private client information.

The LLM is not the authorization mechanism.

Prompt injection is treated as untrusted input and cannot change `RequestContext`, owner state, tool permissions or knowledge scope.

## Verification

The repository CI verifies:

- Python syntax;
- runtime imports;
- bootstrap/deployment script syntax;
- core unit tests;
- Telegram isolation;
- scheduler lifecycle;
- context/retrieval behavior;
- hosted LLM behavior;
- public knowledge filtering;
- Portfolio security boundaries.

No merge or deployment should be considered successful without actual CI evidence.

## Local development

Use the repository's dependency manifests and configure a local `~/.nexo.env` from `.nexo.env.example`.

Never commit `~/.nexo.env` or real credentials.

A typical hosted-runtime startup is:

```bash
python -m uvicorn portfolio_api:app --host 0.0.0.0 --port 8000
```

Only expose the Portfolio API through an HTTPS reverse proxy or an equivalent secure deployment boundary in production.

## Status

ALEX remains the single coherent orchestration path. Older local-LLM documentation and competing ALEX decision loops are not part of the current architecture.
