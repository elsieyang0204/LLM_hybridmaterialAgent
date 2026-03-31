import os
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from config import config


def _normalize_model_name(model_name: str) -> str:
    name = (model_name or "").strip()
    if name.startswith("models/"):
        return name.split("models/", 1)[1]
    return name


def build_gemini_llm(temperature: float = 0.2) -> ChatGoogleGenerativeAI:
    """Create a Gemini chat model using .env-backed config."""
    if not config.GOOGLE_API_KEY:
        raise ValueError("Missing GOOGLE_API_KEY in .env")

    model_name = _normalize_model_name(config.GEMINI_MODEL)

    return ChatGoogleGenerativeAI(
        model=model_name,
        temperature=temperature,
        google_api_key=config.GOOGLE_API_KEY,
    )


def ping_gemini(prompt: str = "Reply with only: OK") -> Any:
    """Send a minimal request to verify model connectivity."""
    fallback_models = [
        _normalize_model_name(config.GEMINI_MODEL),
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
    ]

    last_error: Exception | None = None
    for model_name in dict.fromkeys(fallback_models):
        try:
            llm = ChatGoogleGenerativeAI(
                model=model_name,
                temperature=0.0,
                google_api_key=config.GOOGLE_API_KEY,
            )
            return llm.invoke(prompt)
        except ChatGoogleGenerativeAIError as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise RuntimeError("Gemini ping failed: no model candidates were attempted")


def langsmith_status() -> dict:
    """Return LangSmith-related runtime flags for quick diagnostics."""
    return {
        "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2"),
        "LANGCHAIN_ENDPOINT": os.getenv("LANGCHAIN_ENDPOINT"),
        "LANGCHAIN_PROJECT": os.getenv("LANGCHAIN_PROJECT"),
        "HAS_LANGCHAIN_API_KEY": bool(os.getenv("LANGCHAIN_API_KEY")),
    }
