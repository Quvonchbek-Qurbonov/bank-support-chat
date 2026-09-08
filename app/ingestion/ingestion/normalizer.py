from __future__ import annotations

import html
import re
from typing import Any

from bs4 import BeautifulSoup


# Keys that normally contain implementation/UI metadata rather than knowledge
# that should be retrieved by the chatbot.
NOISE_KEYS = {
    "id",
    "size",
    "srcSets",
    "backgroundPicture",
    "bannerPicture",
    "mainBannerPicture",
    "picture",
    "screenshots",
    "pageViewersCount",
    "seo",
    "og",
    "properties",
    "tags",
    "type",
    "listType",
    "startFrom",
    "view",
    "desktop",
    "tablet",
    "mobile",
    "styles",
    "className",
}

# Fields whose values can be useful as natural-language content.
TEXT_KEYS = {
    "title",
    "description",
    "text",
    "name",
    "label",
    "value",
    "content",
    "caption",
    "question",
    "answer",
}

# These fields are references rather than knowledge. We keep URLs separately
# in metadata and use them for recursive discovery, but don't embed them.
LINK_KEYS = {
    "url",
    "path",
    "buttonLink",
    "mainPageUrl",
    "externalLink",
    "documentUrl",
    "fileUrl",
    "downloadUrl",
}


def strip_html(value: str) -> str:
    """Convert HTML-ish strings from the API to readable text."""
    value = html.unescape(value)
    soup = BeautifulSoup(value, "lxml")

    # Preserve basic block/list boundaries instead of collapsing everything
    # into one line. This matters for FAQ answers and tariff lists.
    for tag in soup.find_all(["br"]):
        tag.replace_with("\n")
    for tag in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
        tag.insert_before("\n")
        tag.insert_after("\n")

    text = soup.get_text(" ", strip=False)
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return normalize_whitespace(text)


def normalize_whitespace(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def clean_scalar(value: Any) -> str:
    if isinstance(value, str):
        return strip_html(value)
    return str(value).strip()


def extract_page_text(page: dict[str, Any]) -> tuple[str, str | None]:
    """Turn Agrobank page JSON into structured retrieval-friendly text."""
    data = page.get("data") or {}
    if not isinstance(data, dict):
        return "", None

    title: str | None = None
    seo = data.get("seo")
    if isinstance(seo, dict) and isinstance(seo.get("title"), str):
        title = clean_scalar(seo["title"])

    # Some product pages expose the title in a different location.
    if not title:
        for key in ("title", "name"):
            value = data.get(key)
            if isinstance(value, str) and clean_scalar(value):
                title = clean_scalar(value)
                break

    lines: list[str] = []

    code = data.get("code")
    if code:
        lines.append(f"Page: {clean_scalar(code)}")

    if title:
        lines.append(f"Title: {title}")

    breadcrumb = data.get("breadCrumb")
    if isinstance(breadcrumb, list):
        crumbs = []
        for item in breadcrumb:
            if isinstance(item, dict) and isinstance(item.get("title"), str):
                crumb = clean_scalar(item["title"])
                if crumb:
                    crumbs.append(crumb)
        if crumbs:
            lines.append(f"Breadcrumb: {' > '.join(crumbs)}")

    sections = data.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue

            section_title = section.get("title")
            section_code = section.get("code")
            section_label = clean_scalar(section_title) if section_title else clean_scalar(section_code) if section_code else ""
            if section_label:
                lines.append(f"Section: {section_label}")

            blocks = section.get("blocks")
            if not isinstance(blocks, list):
                continue

            for block in blocks:
                if not isinstance(block, dict):
                    continue
                _extract_block(block, lines)

    last_updated = data.get("lastUpdatedDate")
    if last_updated:
        lines.append(f"Source updated: {clean_scalar(last_updated)}")

    text = normalize_whitespace("\n".join(lines))
    return text, title


def _extract_block(block: dict[str, Any], lines: list[str]) -> None:
    block_type = str(block.get("type") or "").strip().lower()
    content = block.get("content")

    if block_type:
        # Keep implementation-specific block names out of the embedding text
        # when they do not add semantic meaning.
        if block_type not in {
            "main-product-banner",
            "text",
            "rich-text",
            "html",
            "faq",
            "list",
        }:
            lines.append(f"Block: {block_type}")

    if block_type == "faq":
        _extract_faq(content, lines)
        return

    if block_type == "list":
        _extract_list(content, lines)
        return

    if block_type in {"text", "rich-text", "html"}:
        _extract_rich_content(content, lines)
        return

    if block_type == "main-product-banner":
        _extract_product_banner(content, lines)
        return

    if block_type == "product-list":
        _extract_product_list(content, lines)
        return

    # Generic fallback for block types we haven't specialized yet.
    if content is not None:
        _flatten_content(content, lines, depth=0)


def _extract_faq(content: Any, lines: list[str]) -> None:
    """Preserve FAQ question/title together with its nested blocks."""
    if not isinstance(content, dict):
        _flatten_content(content, lines, depth=0)
        return

    items = content.get("items")
    if not isinstance(items, list):
        _flatten_content(content, lines, depth=0)
        return

    for item in items:
        if not isinstance(item, dict):
            continue

        item_title = item.get("title") or item.get("question") or item.get("name")
        item_title_text = clean_scalar(item_title) if item_title is not None else ""
        if item_title_text:
            lines.append(f"FAQ: {item_title_text}")

        # FAQ answers are themselves represented as nested blocks.
        nested_blocks = item.get("blocks")
        if isinstance(nested_blocks, list):
            for nested_block in nested_blocks:
                if isinstance(nested_block, dict):
                    _extract_block(nested_block, lines)
        else:
            answer = item.get("answer") or item.get("description") or item.get("text")
            if answer is not None:
                _flatten_content(answer, lines, depth=0)


def _extract_list(content: Any, lines: list[str]) -> None:
    if not isinstance(content, dict):
        _flatten_content(content, lines, depth=0)
        return

    items = content.get("items")
    if not isinstance(items, list):
        _flatten_content(content, lines, depth=0)
        return

    list_type = str(content.get("listType") or "unordered").lower()
    start_from = content.get("startFrom", 1)
    try:
        number = int(start_from)
    except (TypeError, ValueError):
        number = 1

    for index, item in enumerate(items):
        if isinstance(item, (str, int, float, bool)):
            value = clean_scalar(item)
            if not value:
                continue
            if list_type == "ordered":
                lines.append(f"{number + index}. {value}")
            else:
                lines.append(f"- {value}")
        else:
            before = len(lines)
            _flatten_content(item, lines, depth=0)
            if list_type == "ordered" and len(lines) > before:
                first = lines[before]
                if first and not re.match(r"^\d+\.\s", first):
                    lines[before] = f"{number + index}. {first}"


def _extract_rich_content(content: Any, lines: list[str]) -> None:
    if isinstance(content, str):
        text = clean_scalar(content)
        if text:
            lines.append(text)
        return

    if isinstance(content, dict):
        # Common fields used by CMS rich-text blocks.
        for key in ("text", "html", "content", "value"):
            value = content.get(key)
            if isinstance(value, str):
                text = clean_scalar(value)
                if text:
                    lines.append(text)
                    return
        _flatten_content(content, lines, depth=0)
        return

    _flatten_content(content, lines, depth=0)


def _extract_product_banner(content: Any, lines: list[str]) -> None:
    """Extract meaningful product-banner fields and ignore UI-only buttons/images."""
    if not isinstance(content, dict):
        _flatten_content(content, lines, depth=0)
        return

    for key in ("title", "description", "subtitle", "price", "priceDescription", "currency"):
        value = content.get(key)
        if value is None:
            continue
        text = clean_scalar(value)
        if text:
            label = key.replace("camel", "").replace("_", " ").strip().capitalize()
            lines.append(f"{label}: {text}")


def _extract_product_list(content: Any, lines: list[str]) -> None:
    if not isinstance(content, dict):
        _flatten_content(content, lines, depth=0)
        return

    # Product lists commonly use items, products, or data.
    items = content.get("items") or content.get("products") or content.get("data")
    if not isinstance(items, list):
        _flatten_content(content, lines, depth=0)
        return

    for item in items:
        if not isinstance(item, dict):
            _flatten_content(item, lines, depth=0)
            continue

        product_name = item.get("title") or item.get("name")
        product_name_text = clean_scalar(product_name) if product_name is not None else ""
        if product_name_text:
            lines.append(f"Product: {product_name_text}")

        for key in ("description", "advantages", "categories"):
            value = item.get(key)
            if value is None:
                continue
            lines.append(f"{key.capitalize()}:")
            _flatten_content(value, lines, depth=0)


def _flatten_content(value: Any, lines: list[str], depth: int, key: str | None = None) -> None:
    if depth > 12:
        return

    if isinstance(value, dict):
        for child_key, child_value in value.items():
            if child_key in NOISE_KEYS or child_key in LINK_KEYS:
                continue
            _flatten_content(child_value, lines, depth + 1, child_key)
        return

    if isinstance(value, list):
        for item in value:
            _flatten_content(item, lines, depth + 1, key)
        return

    if isinstance(value, (str, int, float, bool)):
        text = clean_scalar(value)
        if not text or text.lower() in {"null", "none", "true", "false"} and isinstance(value, str):
            return

        if key in NOISE_KEYS or key in LINK_KEYS:
            return

        if key in TEXT_KEYS and key not in {None, "content"}:
            lines.append(f"{key.replace('_', ' ').capitalize()}: {text}")
        else:
            lines.append(text)


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    if not text:
        return []
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Invalid chunk size/overlap")

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n{paragraph}"
        if len(candidate) <= size:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= size:
            current = paragraph
        else:
            start = 0
            while start < len(paragraph):
                end = min(start + size, len(paragraph))
                chunks.append(paragraph[start:end])
                if end == len(paragraph):
                    break
                start = max(0, end - overlap)
            current = ""

    if current:
        chunks.append(current)

    if overlap == 0 or len(chunks) <= 1:
        return chunks

    adjusted = [chunks[0]]
    for previous, current in zip(chunks, chunks[1:]):
        tail = previous[-overlap:]
        adjusted.append(f"{tail}\n{current}")
    return adjusted
