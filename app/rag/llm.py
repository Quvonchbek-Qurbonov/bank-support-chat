from __future__ import annotations

from groq import Groq

from app.core.config import get_settings


SYSTEM_PROMPT = """
You are Agrobank's website support assistant.

Answer ONLY from the supplied official Agrobank website context.

Do not invent:
- rates
- fees
- limits
- requirements
- dates
- products
- policies

If the context does not contain enough information, explicitly say that
the available Agrobank website data does not provide the answer.

Always prefer the newest information when multiple chunks conflict.

Keep the answer concise and factual.
""".strip()


class LLMService:
    def __init__(self) -> None:
        settings = get_settings()

        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY must be configured")

        self.client = Groq(
            api_key=settings.groq_api_key
        )

        self.model = settings.groq_model

    def answer(self, question: str, context: list[dict]) -> str:
        context_text = "\n\n".join(
            (
                f"SOURCE {i + 1}\n"
                f"Title: {item.get('title') or ''}\n"
                f"URL: {item.get('page_url') or ''}\n"
                f"Content:\n{item.get('text') or ''}"
            )
            for i, item in enumerate(context)
        )

        prompt = (
            "Official Agrobank website context:\n\n"
            f"{context_text}\n\n"
            f"Question: {question}"
        )

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
            max_completion_tokens=500,
            top_p=1,
            reasoning_effort="low",
            include_reasoning=False,
            stream=False,
        )

        return completion.choices[0].message.content or (
            "I could not generate an answer from the available website data."
        )