from __future__ import annotations

from groq import Groq
from app.core.config import settings


SYSTEM_PROMPT = """
You are Agrobank's virtual customer support assistant. Provide accurate, polite, and factual responses based strictly on official data.

CRITICAL RULES:
1. Grounding: For any question asking about Agrobank's products, services, rates, fees, limits, eligibility, procedures, or other factual bank information, answer ONLY using information inside the <context> block. If the context lacks sufficient detail for that question, state: "I don't have that specific information based on our current website data. Please call Agrobank support at 1216 or visit your nearest branch for assistance."
2. Small talk: If the user's message is a greeting, thanks, farewell, or general conversation that is not asking for specific bank information (e.g. "hello", "how are you", "thank you"), respond briefly and naturally, and invite them to ask about Agrobank's products or services. Do not use the rule 1 disclaimer for these messages — no factual claim is being made, so there is nothing to ground.
3. Zero Invention: Never assume, calculate, or invent rates, fees, limits, eligibility, dates, or terms.
4. Language Matching: Always reply in the exact language used in the user's current question (Uzbek, Russian, or English), regardless of the context language.
5. Recency: When context chunks conflict, prioritize the information associated with the most recent timestamp.
6. Tone & Structure: Be polite, concise, and direct. Use short bullet points for multi-step procedures or product features.
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
        context_text = (
            "\n\n".join(
                (
                    f"SOURCE {i + 1}\n"
                    f"Title: {item.get('title') or ''}\n"
                    f"URL: {item.get('page_url') or ''}\n"
                    f"Content:\n{item.get('text') or ''}"
                )
                for i, item in enumerate(context)
            )
            if context
            else "No matching website content was found for this question."
        )
        print(history)

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