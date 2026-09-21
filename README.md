# NEXO-MANAGER

NEXO-MANAGER is a Python AI orchestration runtime whose active user-facing identity is **ALEX**.

The current production path is:

```text
USER
 ↓
TELEGRAM / FUTURE CHANNELS
 ↓
ALEX
 ↓
EXECUTIVE PLANNER / ROUTER
 ↓
HOSTED LLM PROVIDER
 ↓
OPENROUTER
 ↓
CONFIGURED HOSTED MODEL
 ↓
TOOLS / EXECUTION / OPENHANDS WHEN ACTUALLY CONFIGURED
```

NEXO is retained as the internal architecture/compatibility name. It is **not** a separate local-model runtime.

## Current architecture

```text
Telegram
   |
   v
Load guard + input gatekeeper
   |
   v
Security guardrails + permission boundary
   |
   +----> SQLite / semantic memory
   |
   v
ALEX / Executive Planner
   |
   v
LLM Router
   |
   v
OpenRouter hosted provider
   |
   v
Configured hosted model
   |
   v
Registered tools (only when authorized)
   |
   v
Verified response + bounded persistence
```

The core rule remains:

> **The model reasons. The backend controls. Policy authorizes. Registered tools execute. Runtime evidence verifies.**

## Hosted LLM runtime

`services/llm_provider.py` is the provider boundary. The active implementation accepts **OpenRouter only** and reads the configured model from the normal runtime environment.

The real environment is outside Git:

```text
~/.nexo.env
```

The repository does not require a local LLM server, local model download, local model inference, or automatic local-model fallback.

Do not modify or expose the real environment file. The safe template is:

```text
.nexo.env.example
```

It documents the hosted variables:

```text
LLM_PROVIDER=openrouter
LLM_API_KEY=
LLM_MODEL=
LLM_BASE_URL=https://openrouter.ai/api/v1
```

The configured `LLM_MODEL` is intentionally not hard-coded in the repository.

## Telegram entrypoint

The historical filename is:

```bash
python telegram_llama.py
```

The filename is preserved for compatibility. It is the Telegram/ALEX runtime entrypoint, not a local-LLaMA launcher.

Telegram startup uses the existing asynchronous scheduler lifecycle:

- `_post_init(application)` starts the scheduler;
- `_post_shutdown(application)` stops it;
- `Application.builder().post_init(...).post_shutdown(...)` wires both hooks.

The entrypoint must not call `scheduler.start()` synchronously before Telegram creates its running event loop.

## Context budget

`services/context_budget.py` keeps the core system prompt and current user request mandatory while allowing optional memory, knowledge, history, and tool context to be discarded when necessary.

This prevents oversized optional context from blocking a valid current request.

## Tools and security

The cleanup does not remove existing security boundaries. The runtime retains:

- owner/user isolation;
- input and security guardrails;
- registered tool schemas;
- bounded tool calls;
- bounded tool results;
- explicit confirmation for sensitive actions;
- truthful verification of tool success;
- SQLite/semantic memory boundaries.

A model response is never treated as permission.

## Local-model legacy status

The audit found historical local-model references in configuration, prompts, documentation, bootstrap detection, and Termux deployment checks.

They are now classified as follows:

| Component | Classification | Current status |
|---|---|---|
| OpenRouter provider | A — Active hosted runtime | Active |
| LLM router/provider abstraction | C/D — Shared/future infrastructure | Preserved |
| Executive Planner | A — Active hosted runtime | Active |
| `telegram_llama.py` | A — Active entrypoint; historical filename | Preserved |
| Local LLaMA/llama.cpp detection in bootstrap | B — Legacy local runtime | Removed |
| GGUF model discovery in bootstrap | B — Legacy local runtime | Removed |
| Local Qwen/DeepSeek role names | D — Future/legacy role templates | Preserved but explicitly inactive |
| Whisper/STT local adapters | C — Non-LLM voice infrastructure | Preserved |
| Historical `nexo-llama` PM2 name | C — Compatibility surface | Preserved; not treated as a local model server |
| Local-model documentation | B — Legacy documentation | Updated |

No local LLM dependency was found in the current Python dependency manifests. No dependency was removed blindly.

## Termux / Android

The existing Termux Python runtime remains supported. The bootstrap does not create a second Termux virtual environment.

The safe deployment scripts preserve the historical PM2 process name `nexo-llama` for compatibility, but the updater no longer probes `127.0.0.1:8080/health` as a local LLM health dependency. It validates the configured hosted provider and PM2 runtime instead.

Any external startup script that still launches a local LLM is outside this repository and must be migrated separately; this repository no longer requires such a server for the ALEX hosted path.

## Voice

Voice/STT is separate from LLM inference. Optional local Whisper/faster-whisper adapters remain because they are speech-to-text components, not local LLM execution. They are not required for the Telegram text runtime.

## Testing

Run:

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

CI also validates Ubuntu, macOS, and Windows.

A successful repository test run does **not** prove live Telegram/OpenRouter credentials. Live verification requires the real runtime environment and must be reported separately.

## Safety

Never commit or print:

- Telegram tokens;
- API keys;
- passwords;
- OTPs;
- authorization headers;
- private keys;
- `~/.nexo.env`;
- runtime databases;
- model files;
- runtime logs.

No API key, bot token, or real model value is hard-coded by this cleanup.
