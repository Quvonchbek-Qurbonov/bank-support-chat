from functools import lru_cache
from transformers import AutoTokenizer
from app.core.config import settings


@lru_cache(maxsize=1)
def get_tokenizer():
    """
    Load the tokenizer once and reuse it.
    """
    return AutoTokenizer.from_pretrained(settings.groq_final_model)


def count_text_tokens(text: str) -> int:
    """
    Count tokens in plain text.
    """
    tokenizer = get_tokenizer()
    return len(tokenizer.encode(text, add_special_tokens=False))


def count_message_tokens(messages: list[dict]) -> int:
    """
    Count tokens for the complete chat prompt, including
    system/user messages and chat-template formatting.
    """
    tokenizer = get_tokenizer()

    token_ids = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
    )

    return len(token_ids)