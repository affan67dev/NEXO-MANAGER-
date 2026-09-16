from __future__ import annotations

from services.llm_provider import LLMConfig


def check_llm_configuration() -> dict[str, object]:
    try:
        config = LLMConfig.from_env()
        return {"ok": True, "provider": config.provider, "model": config.model}
    except RuntimeError as exc:
        return {"ok": False, "provider": None, "model": None, "category": str(exc)}


if __name__ == "__main__":
    print(check_llm_configuration())
