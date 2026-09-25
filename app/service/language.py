from fast_langdetect import detect


SUPPORTED_LANGUAGES = {"uz", "ru", "en"}


class LanguageDetectionError(Exception):
    pass


def detect_language(text: str) -> str:
    if not text or not text.strip():
        raise LanguageDetectionError("Text is empty")

    try:
        result = detect(
            text.strip(),
            model="lite",
            k=1,
        )
    except Exception as exc:
        raise LanguageDetectionError(
            f"Language detection failed: {exc}"
        ) from exc

    if not result:
        raise LanguageDetectionError("No language detected")

    language = result[0].get("lang", "").lower()

    if language not in SUPPORTED_LANGUAGES:
        raise LanguageDetectionError(
            f"Unsupported language detected: {language}"
        )

    return language