"""Thin wrapper around the Google Gemini API (free tier), shared by V1 and V2.

The API key is read from the environment (or a local .env file that is
git-ignored). It is never hard-coded.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

# Load <repo>/.env if present (silently ignored otherwise).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_MODEL = "gemini-flash-latest"


class LLMUnavailable(Exception):
    """Raised when the LLM cannot be used (no key, network error, quota...)."""


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def model_name() -> str:
    return os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def generate(
    system_prompt: str,
    messages: list[dict],
    temperature: float = 0.7,
    json_mode: bool = False,
    retries: int = 2,
) -> str:
    """Send a conversation to Gemini and return the reply text.

    `messages` is a list of {"role": "user" | "assistant", "content": str}.
    Raises LLMUnavailable on any failure so callers can degrade gracefully.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise LLMUnavailable(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name(), contents=contents, config=config
            )
            text = (response.text or "").strip()
            if not text:
                raise LLMUnavailable("The model returned an empty response.")
            return text
        except LLMUnavailable as exc:
            last_error = exc
        except Exception as exc:  # network, quota, safety block, ...
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    raise LLMUnavailable(f"Gemini request failed: {last_error}")
