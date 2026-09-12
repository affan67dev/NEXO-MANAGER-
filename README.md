# NEXO-MANAGER

NEXO-MANAGER is a **local-first Python AI assistant runtime** built around a local LLM endpoint, Telegram, controlled tools, SQLite-backed memory, security gates, and bounded execution.

The repository also contains a cross-platform bootstrap layer for **Windows, Linux, macOS, and Termux/Android**, plus a CI and safe deployment system for the existing Termux runtime.

> **Important:** NEXO is local-first, not completely offline. Local LLM inference can run without an internet connection when the model and runtime are already installed, but Telegram, GitHub operations, web search, and other external services require network access when used.

---

## What NEXO-MANAGER solves

A local AI assistant normally needs several pieces to work together safely: an LLM runtime, application logic, memory, permissions, tools, configuration, and operational checks.

NEXO-MANAGER provides those pieces as a controlled Python application instead of allowing the model itself to become the authority.

The central design rule is:

```text
The model reasons.
The backend controls.
Policy authorizes.
Registered tools execute.
Runtime evidence verifies.
```

This keeps model output separate from permissions and system actions.

---

## Current architecture

```text
Telegram / supported input
        |
        v
Load guard + input gatekeeper
        |
        v
Security guardrails + permission boundary
        |
        +----> user/session memory
        |           |
        |           v
        |       SQLite / semantic memory
        |
        v
Executive planner
        |
        v
LLM router
   |             |
   |             +---- optional Qwen endpoint
   |
   +------------------ primary Llama endpoint
        |
        v
Validated registered tools (when authorized)
        |
        v
Response + bounded persistence
```

Operationally, the Termux deployment path is separate:

```text
GitHub main SHA
      |
      v
CI result for that SHA
      |
      v
Immutable release worktree
      |
      v
Compile + unit tests
      |
      v
Safe runtime synchronization
      |
      v
Restart nexo-backend + nexo-llama
      |
      v
llama health check + PM2 status
      |
   +--+--+
   |     |
 PASS   FAIL
   |     |
   v     v
Keep   restore previous release
       + restart + health check
```

---

# Features

The following are implemented in the current repository.

| Feature | Status | Notes |
|---|---|---|
| Local LLM inference | Implemented | NEXO talks to an already-running OpenAI-compatible local endpoint. |
| Llama integration | Implemented | Default endpoint is `http://127.0.0.1:8080/v1/chat/completions`. |
| Optional Qwen fallback | Implemented | Opt-in secondary endpoint; no second model is started automatically. |
| Telegram interface | Implemented | `telegram_llama.py` uses `python-telegram-bot` and polling. |
| SQLite memory | Implemented | Session/conversation memory uses `data/memory.db`. |
| Semantic memory | Implemented | ChromaDB-backed semantic memory is optional at runtime and falls back to SQLite search. |
| Security gates | Implemented | Input, security, and permission checks run before planner/tool execution. |
| Tool validation | Implemented | Registered tools use schemas and permission boundaries. |
| Health check | Implemented | `core/health.py` checks the local llama-server health endpoint. |
| Cross-platform bootstrap | Implemented | `bootstrap.sh`, `bootstrap.bat`, and `scripts/bootstrap_nexo.py`. |
| CI testing | Implemented | GitHub Actions tests Ubuntu, macOS, and Windows. |
| Safe Termux deployment | Implemented | SHA polling, CI gating, immutable releases, bounded rollback. |
| Automatic rollback | Implemented | Deployment can restore the previous known-good release after restart/health/finalization failure. |
| Voice pipeline | Implemented as a component | Uses the configured `WHISPER_CPP_BIN`/model when invoked; it is not the default Telegram text path. |
| Web search | Tool/component | Requires the runtime's configured web-search capability and network access. |

Features marked as components/tools are not claims that every interface automatically enables them.

---

# Requirements

## Python

The bootstrap requires **Python 3.10 or newer**. CI currently uses Python 3.12.

The repository does not enforce a particular CPU architecture. Actual model performance depends heavily on the hardware and GGUF model selected.

## Operating systems

The repository contains platform-aware setup code for:

- Windows
- Linux
- macOS
- Termux on Android

The bootstrap detects the operating system and hardware. Termux is treated specially so the existing Android Python/runtime is not replaced with a second virtual environment.

## Python dependencies

The repository's shared dependency manifest is:

```text
requirements-nexo.txt
```

It currently contains:

```text
requests
psutil
pydantic
fastapi
uvicorn[standard]
httpx
python-dotenv
python-telegram-bot>=22,<23
beautifulsoup4
lxml
apscheduler
aiohttp
numpy
agent-framework
agent-governance-toolkit[full]
chromadb
aider-chat
pypdf
Pillow
pytesseract
```

The bootstrap installs this manifest only when its SHA256 marker shows that the manifest has changed or has not been installed in the desktop setup environment.

## Local LLM runtime

NEXO expects an **already-running OpenAI-compatible LLM HTTP endpoint**. The default Llama endpoint is:

```text
http://127.0.0.1:8080/v1/chat/completions
```

The bootstrap can detect an existing `llama-server` in `PATH`, `~/llama.cpp/build/bin/llama-server`, `~/llama.cpp/llama-server`, or the corresponding repository-local build path.

It does **not** automatically download a GGUF model or build/install llama.cpp.

## GGUF model

The bootstrap looks for a configured `.gguf` file and, when appropriate, checks these locations:

- `NEXO_MODEL_PATH`
- `models/` inside the repository
- `~/models`
- `/sdcard/Download` on Termux

The shared-storage scan on Termux is deliberately non-recursive to avoid expensive phone-wide storage scans.

## RAM / disk

There is no hard RAM minimum enforced by the bootstrap because model requirements depend on the chosen GGUF and runtime configuration.

Larger models require more RAM and may be much slower on mobile hardware. Do not enable a second large model endpoint on a low-memory device unless that runtime is already provisioned and has been tested safely.

## Network requirements

Network access is required for operations that contact external services, including:

- cloning/fetching from GitHub
- GitHub Actions/CI
- Telegram polling
- web search when enabled/used
- external APIs such as configured Tavily search
- downloading Python packages during dependency installation

Local llama-server inference itself can operate without internet access once the runtime, model, and Python dependencies are already available.

---

# Installation

## Before you start

The repository contains two bootstrap wrappers:

```text
bootstrap.sh
bootstrap.bat
```

Both call the same Python setup engine:

```text
scripts/bootstrap_nexo.py
```

The bootstrap is designed to be **idempotent**: running it again should reuse an existing desktop setup and should not create a second Python environment on Termux.

The bootstrap does not create or expose secrets. Runtime secrets are expected outside the repository.

---

## Windows

### 1. Get the repository

Clone the repository with Git, then enter the checkout:

```bat
git clone <your-repository-url>
cd NEXO-MANAGER-
```

Replace `<your-repository-url>` with the repository URL you use. The repository itself does not hard-code a clone command or a release URL.

### 2. Run the Windows bootstrap

From the repository directory:

```bat
bootstrap.bat
```

The wrapper first looks for the Windows `py` launcher and then for `python`. It passes control to `scripts\bootstrap_nexo.py`.

### 3. What the bootstrap does

The setup engine:

1. verifies Python 3.10+;
2. detects OS, architecture, CPU count, RAM and available GPU information;
3. detects an existing llama-server and GGUF model when present;
4. verifies that `data/memory.db` can be opened;
5. creates the desktop virtual environment at:

```text
~/.nexo/setup/venv
```

6. installs `requirements-nexo.txt` when the dependency manifest changed or has not been installed in that setup environment;
7. writes setup state to:

```text
~/.nexo/setup/runtime.json
```

8. optionally supports the profile wizard and Linux desktop shortcut flags.

The bootstrap **does not start Telegram or llama-server automatically** and does not invent a PM2 configuration for desktop systems.

### 4. Configuration

Create your local environment file from `.nexo.env.example` and keep the real file outside Git. The runtime reads:

```text
~/.nexo.env
```

### 5. Verify

Run:

```bat
python scripts\bootstrap_nexo.py --help
```

and, if configured, inspect the printed bootstrap result. A successful run prints:

```text
NEXO bootstrap: PASS
```

### 6. Start NEXO

The repository's Telegram runtime entry point is:

```bat
python telegram_llama.py
```

This requires `TELEGRAM_BOT_TOKEN` to be configured and a usable LLM endpoint to be available.

### 7. Stop/restart

The repository does not provide a Windows service manager or PM2 configuration for desktop startup. Stop the foreground `python telegram_llama.py` process normally, then start it again with the same command.

### Windows troubleshooting

- **Python not found:** install Python 3.10+ and ensure `py` or `python` is available in `PATH`.
- **Bootstrap fails during dependency installation:** check network access and rerun the bootstrap after fixing the package error.
- **Database lock:** stop other NEXO processes using the database and retry.
- **Telegram token error:** configure `TELEGRAM_BOT_TOKEN` in `~/.nexo.env`; never put the real token in Git.
- **LLM unavailable:** verify the configured LLM endpoint is actually running.

---

# Linux

## 1. Get the repository

```bash
git clone <your-repository-url>
cd NEXO-MANAGER-
```

## 2. Run the bootstrap

```bash
chmod +x bootstrap.sh
./bootstrap.sh
```

`bootstrap.sh` resolves its own repository directory and runs `scripts/bootstrap_nexo.py` with `python3` by default.

## 3. Verify setup

```bash
./bootstrap.sh --help
```

For a normal setup:

```bash
./bootstrap.sh
```

The bootstrap creates the desktop environment outside the repository at `~/.nexo/setup/venv`, checks SQLite, detects existing LLM runtime/model files, and records state in `~/.nexo/setup/runtime.json`.

## 4. Optional desktop shortcut

The Python bootstrap supports:

```bash
./bootstrap.sh --desktop-shortcut
```

This is only acted on for a normal Linux desktop with a usable Desktop directory. It does not overwrite a different existing `NEXO.desktop` file.

## 5. Optional profile wizard

```bash
./bootstrap.sh --wizard
```

The wizard accepts `personal` or `shared`. It is skipped on Termux.

## 6. Configure and start

Configure `~/.nexo.env` using `.nexo.env.example`, then run:

```bash
python3 telegram_llama.py
```

A desktop bootstrap does not install or configure a service manager for NEXO.

---

# macOS

The repository's bootstrap uses the same POSIX shell wrapper as Linux and contains macOS-specific hardware detection for memory and displays.

## 1. Get the repository

```bash
git clone <your-repository-url>
cd NEXO-MANAGER-
```

## 2. Run the bootstrap

```bash
chmod +x bootstrap.sh
./bootstrap.sh
```

The bootstrap detects macOS with Python's platform APIs and can use `sysctl` to read physical memory when available. Hardware probes have bounded timeouts.

## 3. Verify

```bash
./bootstrap.sh --help
```

Then configure `~/.nexo.env` from `.nexo.env.example` and start the Telegram runtime with:

```bash
python3 telegram_llama.py
```

The repository does not provide a macOS launch daemon/service definition, so the bootstrap does not claim to install one.

### macOS troubleshooting

- **Permission denied:** make `bootstrap.sh` executable with `chmod +x bootstrap.sh`.
- **Python too old:** use Python 3.10+.
- **Dependency failure:** check package installation output and network access.
- **llama-server not detected:** configure/use an existing compatible `llama-server` installation; the bootstrap does not build it for you.
- **Model not detected:** configure `NEXO_MODEL_PATH` to an existing `.gguf` file.

---

# Termux / Android

**Treat an existing Termux NEXO installation as a production runtime. Do not replace its Python environment or runtime configuration just to use the desktop bootstrap.**

The bootstrap explicitly detects Termux. In Termux it:

- uses the existing `sys.executable`;
- does not create a second `~/.nexo/setup/venv` runtime;
- does not reinstall the repository dependency manifest as part of desktop setup;
- detects the existing `nexo-backend` and `nexo-llama` PM2 processes without reconfiguring them;
- preserves the existing runtime environment and model files.

The repository's safe deployment bootstrap also expects the established Termux runtime to contain `git`, `python`, `pm2`, `curl`, `rsync`, and `crontab`, and expects the existing `nexo-backend` and `nexo-llama` PM2 processes.

## Do not overwrite

Do **not** replace or recreate the existing Android:

- Python runtime
- PM2/startup configuration
- Telegram bot configuration
- `~/.nexo.env`
- SQLite database
- GGUF model
- llama-server configuration

Do not point Android at a newly created desktop virtual environment.

The deployment bootstrap is:

```bash
bash scripts/bootstrap_nexo_deploy.sh
```

It installs the existing safe 30-minute SHA polling schedule and records the current release as known-good. It does not manage `omnix-backend`.

For an already-working Android installation, prefer the established runtime/startup system rather than manually replacing it.

---

# First run

The desktop bootstrap's actual sequence is:

```text
Run bootstrap wrapper
       |
       v
Detect repository + platform/hardware
       |
       v
Detect existing llama-server / GGUF
       |
       v
Verify SQLite can open
       |
       v
Select Python runtime
  |                 |
  | desktop         | Termux
  v                 v
create/reuse       keep existing
~/.nexo/setup/venv Python runtime
       |
       v
Check dependency manifest
       |
       v
Install only when needed (desktop)
       |
       v
Write ~/.nexo/setup/runtime.json
       |
       v
NEXO bootstrap: PASS
```

**Bootstrap is setup/detection, not application startup.** It does not automatically launch Telegram or build/download an LLM model.

At runtime, `telegram_llama.py` performs load control, input inspection, security inspection, permission checks, session/memory lookup, planning, tool execution, persistence, and response delivery.

---

# Model setup

## Llama

NEXO's primary model interface is an OpenAI-compatible local HTTP endpoint configured with:

```text
LLAMA_URL=http://127.0.0.1:8080/v1/chat/completions
```

The repository's health check uses:

```text
http://127.0.0.1:8080/health
```

The application does not itself build llama.cpp or download the model. You must have a compatible local runtime/model available.

## GGUF

The model should be an existing `.gguf` file usable by the selected llama.cpp/llama-server runtime.

You can explicitly configure its path with:

```text
NEXO_MODEL_PATH=/path/to/model.gguf
```

Use a real local path for your machine. Do not commit model files to Git; `.gitignore` excludes `*.gguf`.

## Qwen

Qwen is an **optional secondary endpoint**, not a mandatory second model.

Configuration:

```text
NEXO_QWEN_FALLBACK_ENABLED=false
NEXO_QWEN_URL=
NEXO_QWEN_COMPLEXITY_CHARS=3500
```

When enabled and a different Qwen endpoint is configured:

- ordinary/simple requests use the primary Llama endpoint first;
- sufficiently long/complex requests can prefer Qwen;
- if Qwen fails, the router falls back to Llama;
- if Llama fails, the router can fall back to Qwen;
- if both URLs are the same, the secondary route is disabled;
- the router does **not** start or load a second model itself.

This design avoids forcing two large models into memory. On Android, leave Qwen disabled unless a separately running, memory-safe Qwen service has already been intentionally provisioned and tested.

---

# Online vs offline

## Online

These operations require network access when used:

| Operation | Network needed? |
|---|---:|
| Git clone/fetch/update | Yes |
| GitHub Actions | Yes |
| Telegram polling | Yes |
| Python package installation | Normally yes |
| Tavily/web search | Yes |
| Other external APIs | Yes |
| Local llama-server inference | No, if already installed |
| SQLite/local memory | No |
| Local semantic memory after dependencies/model are installed | No |

## Offline

After dependencies, model files, and local runtime components are already installed, the core local path can operate without internet:

```text
User -> NEXO -> security -> local memory -> local LLM -> response
```

Telegram itself still needs internet because it communicates with Telegram's servers.

GitHub auto-update, package installation, web search, and external API calls cannot operate normally offline.

NEXO should therefore be described as **local-first**, not as a completely offline application.

---

# Configuration

The repository provides:

```text
.nexo.env.example
```

The real runtime configuration is expected at:

```text
~/.nexo.env
```

Never commit the real file.

## Important variables

| Variable | Purpose | Example/safe value |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot authentication | `<telegram-token>` |
| `NEXO_OWNER_TELEGRAM_USER_ID` | Owner/privileged Telegram identity | `<telegram-user-id>` |
| `LLAMA_URL` | Primary OpenAI-compatible LLM endpoint | `http://127.0.0.1:8080/v1/chat/completions` |
| `NEXO_MODEL_PATH` | Optional explicit GGUF path for bootstrap detection | `/path/to/model.gguf` |
| `NEXO_QWEN_FALLBACK_ENABLED` | Enables optional Qwen routing | `false` |
| `NEXO_QWEN_URL` | Secondary Qwen endpoint | `<local-qwen-endpoint>` |
| `NEXO_QWEN_COMPLEXITY_CHARS` | Complexity threshold | `3500` |
| `TAVILY_API_KEY` | Tavily/web-search configuration | `<tavily-key>` |
| `WHISPER_CPP_BIN` | Whisper CLI binary | `whisper-cli` |
| `WHISPER_CPP_MODEL` | Whisper model path | `<whisper-model-path>` |
| `NEXO_TTS_COMMAND` | Optional TTS command configuration | `<local-command>` |
| `NEXO_BRIEFING_HOUR` | Daily briefing hour | `9` |
| `NEXO_BRIEFING_MINUTE` | Daily briefing minute | `0` |

The Telegram runtime loads `~/.nexo.env` without overriding already-present process environment variables.

## System prompt

The repository contains:

```text
system_prompt.txt
```

It defines NEXO's identity, authority model, zero-trust rules, secret handling, tool rules, permission boundaries, memory principles, resource limits, and truthful-response requirements.

Do not casually weaken or remove these controls.

---

# Memory

NEXO has two related local memory components.

## SQLite conversation/session memory

The main runtime uses:

```text
data/memory.db
```

`core/memory_engine.py` creates/verifies session, conversation, and memory structures as needed and isolates records by `user_id` for the runtime APIs that accept it.

Old sessions can be pruned by the scheduler.

## Semantic memory

`core/semantic_memory.py` can use ChromaDB's persistent client at:

```text
data/chroma
```

If ChromaDB is unavailable or its collection cannot be used, the component falls back to a SQLite `LIKE` search.

Sensitive-looking values such as API keys, passwords, OTPs, bearer tokens, private keys and similar credentials are rejected by the memory safety checks.

Memory is context, **not authorization**.

---

# Security model

NEXO does not treat model output as permission.

The important request path is:

```text
Input
  |
  v
Load guard
  |
  v
Input gatekeeper
  |
  v
Security guardrails
  |
  v
Permission boundary
  |
  v
Session + memory context
  |
  v
LLM planner/router
  |
  v
Registered tool + schema validation
  |
  v
Execution
  |
  v
Runtime result
  |
  v
Response
```

The code also applies bounded execution rules such as:

- bounded tool calls per planner run;
- bounded tool-result size;
- bounded context/message sizes;
- load/rate protection;
- owner-only restrictions for privileged tools;
- explicit argument validation;
- secret filtering before memory persistence.

External content and tool output are treated as untrusted data by the system instructions. Do not turn the model into unrestricted shell access or casually weaken the permission layer.

---

# Health checks

`core/health.py` checks the local llama-server health endpoint:

```text
http://127.0.0.1:8080/health
```

To run that module directly:

```bash
python3 core/health.py
```

On Windows, the equivalent is:

```bat
python core\health.py
```

A healthy local endpoint returns an object containing `ok: True` and the HTTP status.

The Termux deployment system performs repeated health checks after restart and also verifies that `nexo-backend` and `nexo-llama` are online in PM2.

---

# Testing

The repository uses Python's built-in `unittest` discovery.

From the repository root:

```bash
python -m unittest discover -s tests -v
```

On Windows:

```bat
python -m unittest discover -s tests -v
```

## Syntax checks

Python syntax/bytecode compilation:

```bash
python -m compileall -q .
```

The CI workflow also checks shell syntax for the deployment/bootstrap shell scripts and verifies the bootstrap help command.

## CI

GitHub Actions is defined in:

```text
.github/workflows/nexo-ci.yml
```

The workflow runs on:

- Ubuntu
- macOS
- Windows

It currently performs:

1. checkout;
2. Python 3.12 setup;
3. runtime smoke-test dependency installation;
4. Python compile check;
5. bootstrap wrapper/help check;
6. deployment shell-script syntax checks;
7. Telegram runtime import check;
8. full `unittest` discovery.

A local test result and a CI result are different checks: CI provides the cross-platform verification that a single local machine cannot provide.

---

# Safe deployment, auto-update and rollback

The Termux deployment system is intentionally conservative.

The main update script is:

```text
scripts/auto_update.sh
```

The one-time Termux deployment bootstrap is:

```text
scripts/bootstrap_nexo_deploy.sh
```

## Update flow

```text
Every 30 minutes
      |
      v
Read remote main SHA
      |
      v
If unchanged -> exit
      |
      v
Require successful NEXO CI for that SHA
      |
      v
Fetch + require fast-forward relationship
      |
      v
Create immutable release worktree
      |
      v
Compile + run repository tests
      |
      v
Install dependencies only if dependency manifests changed
      |
      v
Stage tracked release files safely
      |
      v
Restart only:
  nexo-backend
  nexo-llama
      |
      v
Health + PM2 verification
      |
      v
Finalize main at new SHA
```

The updater refuses to proceed when tracked local changes are present and does not use destructive `git reset --hard`, `git clean`, forced checkout, or force-push operations.

Ignored runtime data such as the local environment, database, logs and model files are kept outside the release's tracked-file synchronization.

## Rollback flow

If restart, health verification, or finalization fails:

```text
Deployment failure
      |
      v
Restore previous release
      |
      v
Restart NEXO processes
      |
      v
Verify health
      |
      v
Keep previous version if recovery succeeds
```

The updater makes one bounded rollback attempt. This is a recovery mechanism, **not a guarantee of zero downtime or perfect recovery**.

The deployment bootstrap explicitly manages only `nexo-backend` and `nexo-llama`; it does not manage `omnix-backend`.

---

# Troubleshooting

## Python missing or too old

Check:

```bash
python3 --version
```

or:

```bash
python --version
```

The bootstrap requires Python 3.10+.

## Dependency installation fails

Run the bootstrap again after checking the package-manager error and network access. The dependency manifest is:

```text
requirements-nexo.txt
```

On desktop, dependency installation is skipped when the manifest's SHA256 matches the recorded setup marker.

On Termux, the desktop bootstrap deliberately does not create a second venv or reinstall the production runtime.

## llama-server is unavailable

The bootstrap only detects an existing server. It does not build one.

Check the expected endpoint:

```text
http://127.0.0.1:8080/health
```

Then run:

```bash
python3 core/health.py
```

If the server is not available, fix the existing llama-server installation/configuration before changing NEXO application code.

## Model not found

Configure an existing GGUF explicitly:

```text
NEXO_MODEL_PATH=/path/to/model.gguf
```

The bootstrap only detects the file; it does not download it.

## Qwen unavailable

Qwen is optional. If it is disabled, NEXO stays on the primary Llama route.

If enabled, verify that `NEXO_QWEN_URL` points to a separate already-running endpoint. If Qwen fails, the router can fall back to Llama.

Do not enable a second large model on a low-memory Android device without testing its memory impact.

## Telegram configuration error

The Telegram runtime raises a configuration error when `TELEGRAM_BOT_TOKEN` is missing.

Check that `~/.nexo.env` contains a valid local value. Never paste the real token into the repository or issue tracker.

## Port already in use

The repository expects the default local LLM endpoint on port `8080`. Check which process is using that port using your operating system's normal process/network diagnostic tools, then reconcile the existing runtime configuration with `LLAMA_URL`.

Do not kill unrelated services blindly.

## SQLite/database problem

The main database is:

```text
data/memory.db
```

Stop competing NEXO processes before repairing or inspecting the database. The bootstrap only verifies that the database can be opened; application memory code owns schema creation/migration.

Always back up important local data before making database changes.

## Permission/security rejection

A rejection can be intentional. The runtime applies input inspection, security guardrails, permission checks, owner boundaries and tool argument validation.

Do not remove these checks simply to make a request execute.

## Bootstrap failure

Run the wrapper directly from the repository root:

```bash
./bootstrap.sh
```

or on Windows:

```bat
bootstrap.bat
```

The Python engine prints the failure reason and exits non-zero when setup cannot be completed.

## Health-check failure after deployment

The safe updater checks both the local llama health endpoint and the required PM2 processes. If deployment health fails, the updater attempts one rollback.

Inspect the deployment log under:

```text
~/.nexo/deploy/auto_update.log
```

The scheduler log is:

```text
~/.nexo/deploy/cron.log
```

These are runtime files and should not be committed.

## Platform-specific problems

- **Windows:** check `py`/`python`, package installation output, and Windows file-locking conflicts.
- **Linux:** check executable permissions on `bootstrap.sh` and available shell/Python tools.
- **macOS:** check Python 3.10+, `sysctl` availability if hardware detection is incomplete, and executable permissions.
- **Termux:** do not replace the existing Python/PM2/model runtime with the desktop setup. Verify the established PM2 processes and deployment prerequisites instead.

---

# Directory structure

The repository contains more components than the simplified tree below; these are the main runtime, configuration, setup, testing and deployment areas:

```text
NEXO-MANAGER-/
├── .github/
│   └── workflows/
│       └── nexo-ci.yml
├── agents/
│   ├── executive_planner.py
│   └── manager/
├── android/
├── automation/
├── config/
├── core/
│   ├── gatekeeper.py
│   ├── health.py
│   ├── load_guard.py
│   ├── memory_engine.py
│   └── semantic_memory.py
├── data/
│   └── memory.db              # local runtime data; ignored by Git
├── memory/
│   ├── init_db.py
│   └── schema.sql
├── services/
│   ├── backup/
│   ├── memory/
│   ├── rag/
│   ├── security/
│   ├── testing/
│   ├── document_parser.py
│   ├── github_safe.py
│   ├── llm_router.py
│   ├── self_healing.py
│   └── voice_pipeline.py
├── scripts/
│   ├── auto_update.sh
│   ├── bootstrap_nexo.py
│   └── bootstrap_nexo_deploy.sh
├── tests/
│   ├── test_bootstrap_setup.py
│   ├── test_llm_routing.py
│   ├── test_stability.py
│   └── other repository tests
├── .gitignore
├── .nexo.env.example
├── bootstrap.bat
├── bootstrap.sh
├── requirements-nexo.txt
├── system_prompt.txt
├── telegram_llama.py
├── tool_registry.py
└── nexo_tools.py
```

`data/memory.db`, GGUF models, logs, secrets and credentials are intentionally excluded from Git by `.gitignore`.

The repository also contains additional application modules not shown in the simplified tree. Use the actual files as the source of truth when developing against a component.

---

# Platform isolation

NEXO has two materially different setup paths.

### Desktop

Windows/Linux/macOS use the cross-platform bootstrap engine and, on non-Termux systems, an isolated environment under:

```text
~/.nexo/setup/venv
```

### Android / Termux

Termux keeps its established Python runtime and production PM2 process setup. The desktop bootstrap detects Termux and deliberately avoids creating a second environment.

### Unrelated projects

The safe Termux deployment code explicitly manages only:

```text
nexo-backend
nexo-llama
```

It does not manage `omnix-backend`.

---

# Contributing and code changes

Before changing NEXO:

1. Inspect the existing implementation and execution path.
2. Make the smallest change that solves the actual problem.
3. Run the relevant unit tests.
4. Run the complete test suite before opening a PR:

   ```bash
   python -m unittest discover -s tests -v
   ```

5. Run the compile check:

   ```bash
   python -m compileall -q .
   ```

6. Review configuration and environment-variable changes.
7. Test the affected runtime path where possible.
8. Review security and permission boundaries when changing tools, routing, memory or external integrations.
9. Commit the change.
10. Open a Pull Request and wait for the repository CI checks.

Changes to core runtime, security, memory, LLM routing, bootstrap, or deployment code deserve both unit tests and runtime verification before deployment.

For Android, treat the existing runtime as production-sensitive: avoid replacing its Python environment, model, database, secrets, PM2 configuration, or startup flow unless the change has been specifically designed and tested for Termux.

---

# Security and data hygiene

Never commit:

- Telegram tokens
- API keys
- passwords
- OTPs
- authorization headers
- private keys
- local databases
- GGUF model files
- runtime logs
- credentials

The repository's `.gitignore` excludes common secret/runtime patterns including `.env`, database files, GGUF files, logs, secrets and credentials.

Use `.nexo.env.example` only as a safe configuration template. Put real values in `~/.nexo.env`.

---

# Current limitations

The repository is intentionally conservative about what the bootstrap promises:

- it detects an existing llama-server; it does not build/download it;
- it detects existing GGUF files; it does not download models;
- Qwen routing is optional and requires a separately running endpoint;
- desktop bootstrap does not configure a desktop service manager;
- Telegram requires internet access;
- web search/external APIs require network access;
- hardware detection reports available information but does not guarantee that a particular model will run well on a machine;
- CI validates repository behavior on GitHub runners, but it is not a substitute for testing the exact physical Android device/model combination.

---

# Disclaimer

NEXO-MANAGER is provided as a software project. Users who modify the source code, configuration, models, dependencies, security rules, or deployment settings are responsible for testing and validating their changes before using the modified system. Unexpected modifications can affect stability, security, compatibility, or data integrity. Always keep a backup and verify changes in a safe environment before deploying them to a live runtime.
