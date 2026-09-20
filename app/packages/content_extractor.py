from __future__ import annotations

import html
import re
from collections.abc import Mapping
from typing import Any

from bs4 import BeautifulSoup


# IMPORTANT:
# Use an allowlist, not only a blacklist.
# New Agrobank CMS/UI block types should be ignored until we explicitly
# decide that they contain knowledge worth indexing.
INDEXABLE_BLOCK_TYPES = {
    "text",
    "paragraph",
    "rich-text",
    "richtext",
    "html",
    "content",
    "heading",
    "quote",
    "faq",
    "accordion",
    "table",
    "list",
}

# These are explicitly non-knowledge/UI/navigation blocks.
IGNORED_BLOCK_TYPES = {
    "image",
    "images",
    "share",
    "tags",
    "social",
    "social-share",
    "next-news-item",
    "previous-news-item",
    "related-news",
    "related-content",
    "navigation",
    "menu",
    "breadcrumb",
    "pagination",
    "banner",
    "button",
    "video",
    "gallery",
}

# Fields that should NEVER become embedding text by themselves.
IGNORED_FIELDS = {
    "id",
    "code",
    "type",
    "block_type",
    "date",
    "created_at",
    "updated_at",
    "center",
    "telegram",
    "news",
    "url",
    "page_url",
    "slug",
}


def strip_html(value: str) -> str:
    """Convert HTML/rich text to normalized plain text."""
    value = html.unescape(value)

    # Remove script/style content before extracting visible text.
    soup = BeautifulSoup(value, "lxml")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(" ", strip=True)

    # Normalize whitespace.
    return re.sub(r"\s+", " ", text).strip()


def _as_text(value: Any) -> str:
    """Convert a scalar HTML/text value into normalized text."""
    if value is None:
        return ""

    if isinstance(value, str):
        return strip_html(value)

    if isinstance(value, (int, float)):
        return str(value)

    return ""


def _normalize_block_type(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    value = value.strip().lower()
    value = value.replace("_", "-").replace(" ", "-")

    return value


def _first_text(block: Mapping[str, Any], *fields: str) -> str:
    """Return the first non-empty textual field."""
    for field in fields:
        value = _as_text(block.get(field))
        if value:
            return value

    return ""


def _extract_table(block: Mapping[str, Any]) -> list[str]:
    """
    Extract useful table content without indexing table IDs/metadata.

    Supports common shapes:
        rows: [{"key": "...", "value": "..."}]
        rows: [["A", "B"], ["C", "D"]]
        cells: [...]
    """
    rows = block.get("rows")

    if rows is None:
        rows = block.get("data")

    if rows is None:
        return []

    result: list[str] = []

    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping):
                values: list[str] = []

                for key, value in row.items():
                    if key in IGNORED_FIELDS:
                        continue

                    text = _as_text(value)

                    if text:
                        values.append(text)

                if values:
                    result.append(" | ".join(values))

            elif isinstance(row, list):
                values = [_as_text(value) for value in row]
                values = [value for value in values if value]

                if values:
                    result.append(" | ".join(values))

            elif isinstance(row, str):
                text = _as_text(row)

                if text:
                    result.append(text)

    return result


def _extract_list(block: Mapping[str, Any]) -> list[str]:
    items = block.get("items")

    if not isinstance(items, list):
        return []

    result: list[str] = []

    for item in items:
        if isinstance(item, Mapping):
            text = _first_text(
                item,
                "text",
                "content",
                "title",
                "label",
                "value",
            )
        else:
            text = _as_text(item)

        if text:
            result.append(text)

    return result


def _extract_faq_or_accordion(block: Mapping[str, Any]) -> list[str]:
    result: list[str] = []

    question = _first_text(
        block,
        "question",
        "q",
        "title",
        "heading",
        "label",
    )

    answer = _first_text(
        block,
        "answer",
        "a",
        "text",
        "content",
        "description",
    )

    if question:
        result.append(f"Question: {question}")

    if answer:
        result.append(f"Answer: {answer}")

    # Some accordions contain multiple items.
    items = block.get("items")

    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                continue

            item_question = _first_text(
                item,
                "question",
                "q",
                "title",
                "heading",
                "label",
            )

            item_answer = _first_text(
                item,
                "answer",
                "a",
                "text",
                "content",
                "description",
            )

            if item_question:
                result.append(f"Question: {item_question}")

            if item_answer:
                result.append(f"Answer: {item_answer}")

    return result


def extract_block_content(block: Mapping[str, Any]) -> list[str]:
    """
    Extract only knowledge-bearing content from one CMS block.
    """
    block_type = _normalize_block_type(
        block.get("type")
        or block.get("block_type")
        or block.get("kind")
        or block.get("name")
    )

    if block_type in IGNORED_BLOCK_TYPES:
        return []

    # Known content blocks.
    if block_type in {"faq", "accordion"}:
        return _extract_faq_or_accordion(block)

    if block_type == "table":
        title = _first_text(block, "title", "heading")
        rows = _extract_table(block)

        result: list[str] = []

        if title:
            result.append(title)

        result.extend(rows)
        return result

    if block_type == "list":
        title = _first_text(block, "title", "heading")
        items = _extract_list(block)

        result = []

        if title:
            result.append(title)

        result.extend(f"- {item}" for item in items)

        return result

    # Generic text/content block.
    title = _first_text(
        block,
        "title",
        "heading",
        "subtitle",
    )

    text = _first_text(
        block,
        "text",
        "content",
        "html",
        "description",
        "value",
    )

    result = []

    if title:
        result.append(title)

    if text and text != title:
        result.append(text)

    # IMPORTANT:
    # Unknown block types are allowed only when they actually contain a
    # meaningful content field. This prevents metadata-only blocks such as
    # next-news-item from being embedded.
    if not result:
        return []

    if block_type and block_type not in INDEXABLE_BLOCK_TYPES:
        # Unknown CMS block: only keep it when it has actual text content.
        # Never index title-only metadata.
        if not text:
            return []

    return result


def _normalize_sequence(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, Mapping):
        return list(value.values())

    return []


def extract_indexable_content(page: Mapping[str, Any]) -> str:
    """
    Convert an Agrobank API page into clean text suitable for chunking
    and embedding.

    The output deliberately excludes:
        - breadcrumbs
        - dates
        - image blocks
        - share blocks
        - tags
        - next/previous/related news
        - IDs and codes
        - social metadata
        - navigation metadata
    """
    output: list[str] = []

    page_title = _first_text(
        page,
        "title",
        "name",
    )

    sections = _normalize_sequence(page.get("sections"))

    # Normal page title is useful semantic context.
    if page_title:
        output.append(f"Title: {page_title}")

    for section in sections:
        if not isinstance(section, Mapping):
            continue

        section_title = _first_text(
            section,
            "title",
            "name",
            "heading",
        )

        blocks = _normalize_sequence(section.get("blocks"))

        for block in blocks:
            if not isinstance(block, Mapping):
                continue

            block_text = extract_block_content(block)

            if not block_text:
                continue

            # Attach section context to actual knowledge.
            if section_title:
                output.append(f"Section: {section_title}")

            output.extend(block_text)

    # Some pages may contain top-level content instead of sections.
    if not sections:
        top_level_content = extract_block_content(page)

        if top_level_content:
            output.extend(top_level_content)

    # Normalize duplicates caused by repeated block metadata.
    cleaned: list[str] = []
    previous = None

    for value in output:
        value = value.strip()

        if not value:
            continue

        if value == previous:
            continue

        cleaned.append(value)
        previous = value

    return "\n\n".join(cleaned)