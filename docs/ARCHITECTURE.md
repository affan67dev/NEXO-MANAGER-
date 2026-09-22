# ALEX / NEXO ARCHITECTURE

The active production architecture is:

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

ALEX is the user-facing identity. NEXO Manager is the internal compatibility/orchestration layer.

## Runtime boundaries

- `services/llm_provider.py` owns the hosted-provider transport and currently accepts only `openrouter`.
- `services/llm_router.py` is the provider-selection boundary. It currently uses one configured provider and never activates a secondary local model.
- `agents/executive_planner.py` performs planning, context fitting, tool-call limits, and verified execution.
- `telegram_llama.py` is the historical Telegram entrypoint name. It starts the ALEX runtime and must not be interpreted as a local-LLaMA launcher.
- `services/context_budget.py` keeps the core system prompt and current user request mandatory while allowing optional context/history to be discarded.
- Security, owner isolation, registered tools, and bounded execution remain independent of the model provider.

## Local-model status

Local LLaMA/DeepSeek/Qwen inference is not part of the active production path. Historical role names, prompts, deployment process names, and compatibility references may remain where removing them would break migration compatibility. They must not be used to start or silently fall back to a local model.

## Future extensibility

The provider and router abstractions remain intentionally small so another hosted provider/model can be added later without changing ALEX's identity or authorization boundaries. Multi-model routing is not active in the current runtime.
