# NEXO — Local Personal AI

Local-first personal AI assistant.

## Architecture

Telegram / Voice / Android / Laptop
        ↓
Python Backend
        ↓
Memory + Tool Router
        ↓
SQLite / Future Vector Search / Tools
        ↓
Relevant Context
        ↓
Local Llama
        ↓
Response

## Current Components

- llama.cpp local inference
- llama-server
- Telegram interface
- NEXO system instructions
- SQLite memory foundation
- Memory safety rules
- Future voice layer
- Future web tools
- Future Android tools

## Security

Secrets and local databases must never be committed to Git.
