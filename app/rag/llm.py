from __future__ import annotations

from groq import Groq
from app.core.config import settings


SYSTEM_PROMPT = """
You are Agrobank's virtual customer support assistant. Provide accurate, polite, and factual responses based strictly on official data.

CRITICAL RULES:
1. Grounding: Answer ONLY using information inside the <context> block. If the context lacks sufficient detail, state: "I don't have that specific information based on our current website data. Please call Agrobank support at 1216 or visit your nearest branch for assistance."
2. Zero Invention: Never assume, calculate, or invent rates, fees, limits, eligibility, dates, or terms.
3. Language Matching: Always reply in the exact language used in the user's question (Uzbek, Russian, or English), regardless of the context language.
4. Recency: When context chunks conflict, prioritize the information associated with the most recent timestamp.
5. Tone & Structure: Be polite, concise, and direct. Use short bullet points for multi-step procedures or product features.
""".strip()


class LLMService:
    def __init__(self) -> None:

        self.client = Groq(
            api_key=settings.groq_api_key
        )

        self.model = settings.groq_model

    def answer(
            self,
            question: str,
            context: list[dict],
            history: list[dict] | None = None,
    ) -> str:
        print(history)
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

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": prompt})

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
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