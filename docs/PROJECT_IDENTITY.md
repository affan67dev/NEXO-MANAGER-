# NEXO-MANAGER — Project Identity

## Project

**NEXO-MANAGER** is a Python AI orchestration runtime whose active user-facing identity is **ALEX**.

The production path is provider-agnostic at the orchestration boundary but currently configured for:

**ALEX → Executive Planner/Router → Hosted LLM Provider → OpenRouter → configured hosted model → registered tools/execution.**

NEXO remains as an internal architectural and compatibility name. It is not a separate local-model runtime.

## Core principles

> **The model reasons. The backend controls. Policy authorizes. Registered tools execute. Runtime evidence verifies.**

The system combines:

- Telegram and future channel boundaries;
- executive planning and routing;
- hosted LLM transport;
- SQLite-backed session/conversation memory;
- optional semantic memory;
- security and permission gates;
- validated registered tools;
- health/configuration checks;
- CI verification;
- safe Termux deployment.

## Compatibility

The historical file name `telegram_llama.py`, internal NEXO module names, and selected legacy role/template names may remain because they are compatibility surfaces. They do not mean the active runtime uses local LLaMA inference.

## Local-model policy

The active runtime does not require, start, download, load, or silently fall back to local LLaMA, DeepSeek, or Qwen models. Future model abstractions may remain, but no local model routing is active.

## Repository

`https://github.com/affan67dev/NEXO-MANAGER-`

## Developer

AFFAN MIR (`affan67dev`)
