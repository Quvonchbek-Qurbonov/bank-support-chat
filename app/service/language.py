from fast_langdetect import detect


SUPPORTED_LANGUAGES = {"uz", "ru", "en"}
MIN_CONFIDENCE = 0.65


class LanguageDetectionError(ValueError):
    """Raised when the user's language cannot be reliably detected."""


def detect_language(text: str) -> str:
    text = text.strip()

    if not text:
        raise LanguageDetectionError("Question cannot be empty.")

    results = detect(
        text=text,
        model="lite",
        k=1,
    )

    if not results:
        raise LanguageDetectionError(
            "Could not detect the question language."
        )

    result = results[0]
    language = result["lang"]
    score = float(result["score"])

    if language not in SUPPORTED_LANGUAGES:
        raise LanguageDetectionError(
            "Only Uzbek, Russian, and English are supported."
        )

    if score < MIN_CONFIDENCE:
        raise LanguageDetectionError(
            "Could not confidently detect the question language. "
            "Please ask your question in Uzbek, Russian, or English."
        )

    return language