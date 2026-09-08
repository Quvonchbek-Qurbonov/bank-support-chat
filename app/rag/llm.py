from __future__ import annotations
import random
import time

from google import genai
from google.genai import errors, types
from google import genai
from google.genai import types

from app.core.config import get_settings


SYSTEM_PROMPT = """
You are Agrobank's website support assistant.

Answer ONLY from the supplied official Agrobank website context.
Do not invent rates, fees, limits, requirements, dates, products, or policies.
If the context does not contain enough information, explicitly say that the
available Agrobank website data does not provide the answer.
Always prefer the newest information when multiple chunks conflict.
Keep the answer concise and factual.
""".strip()


class LLMService:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY must be configured")

        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model

    def answer(self, question: str, context: list[dict]) -> str:
        context_text = "\n\n".join(
            f"SOURCE {i + 1}\nTitle: {item.get('title') or ''}\nURL: {item.get('page_url') or ''}\n"
            f"Content:\n{item.get('text') or ''}"
            for i, item in enumerate(context)
        )

        prompt = (
            "Official Agrobank website context:\n\n"
            f"{context_text}\n\n"
            f"Question: {question}"
        )

        max_retries = 3

        for attempt in range(max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0,
                    ),
                )

                return response.text or (
                    "I could not generate an answer from the available website data."
                )

            except errors.APIError as exc:
                # Retry only temporary server-side errors.
                if exc.code != 503:
                    raise

                # No more retries.
                if attempt == max_retries:
                    return (
                        "Gemini is temporarily unavailable because the model is "
                        "experiencing high demand. Please try again shortly."
                    )

                # Exponential backoff + small random jitter.
                delay = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
        return "NO ANSWER"
