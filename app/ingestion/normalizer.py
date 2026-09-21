from __future__ import annotations

import html
import re
from typing import Any

from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Block-level rules
# ---------------------------------------------------------------------------

# Blocks that are pure chrome / navigation / cross-links to OTHER pages.
# They never describe the page they sit on, so they must never reach an embedding.
SKIP_BLOCK_TYPES: set[str] = {
    "share",
    "socials",
    "social",
    "next-news-item",
    "prev-news-item",
    "previous-news-item",
    "next-page",
    "other-news",
    "similar-news",
    "related-news",
    "last-news",
    "tags",
    "breadcrumb",
    "breadcrumbs",
    "pagination",
    "search",
    "filter",
    "filters",
    "subscribe",
    "subscription",
    "banner",
    "main-banner",
    "background",
    "slider",
    "carousel",
    "gallery",
    "video",
    "map",
    "mobile-app",
    "app-download",
    "advertising",
    "partners-slider",
}

# Blocks that only carry alt text / a caption that duplicates the section title.
# Kept separate so you can flip one flag instead of editing the set above.
SKIP_MEDIA_BLOCKS = True
MEDIA_BLOCK_TYPES: set[str] = {"image", "picture", "photo", "icon", "logo"}


# ---------------------------------------------------------------------------
# Key-level rules
# ---------------------------------------------------------------------------

# Structural / presentational / identity keys: never emit their value.
DROP_KEYS: set[str] = {
    # identity & ordering
    "id", "uuid", "guid", "key", "slug", "code", "parentId", "sectionId",
    "blockId", "order", "sort", "sortOrder", "weight", "index",
    # links & media
    "url", "path", "link", "href", "buttonLink", "mainPageUrl", "externalLink",
    "src", "srcSet", "srcSets", "image", "picture", "images", "pictures",
    "icon", "iconName", "logo", "file", "fileName", "fileSize", "mimeType",
    "extension", "thumbnail", "preview", "backgroundPicture", "bannerPicture",
    "mainBannerPicture", "screenshots", "video", "poster",
    # presentation
    "type", "variant", "view", "viewType", "template", "layout", "align",
    "alignment", "textAlign", "direction", "color", "bgColor", "background",
    "backgroundColor", "theme", "style", "size", "width", "height", "class",
    "className", "target", "rel", "anchor", "format", "mask", "placeholder",
    # flags & counters
    "isActive", "isVisible", "visible", "hidden", "enabled", "disabled",
    "required", "readonly", "checked", "selected", "default", "isMain",
    "isNew", "isHot", "viewsCount", "viewCount", "views", "pageViewersCount",
    "likesCount", "commentsCount", "count", "total",
    # seo / meta
    "seo", "og", "meta", "metaTitle", "metaDescription", "keywords",
    "properties", "tags", "lang", "locale", "language",
}

# Keys whose value is real content and is worth a label in the output.
LABELLED_KEYS: set[str] = {
    "title", "subtitle", "heading", "name", "fullName", "position",
    "description", "shortDescription", "text", "content", "body",
    "question", "answer", "caption", "alt", "label", "buttonTitle",
    "address", "phone", "email", "workingHours",
}

# Numeric keys that genuinely matter for a bank (rates, terms, limits).
# Every other number is dropped.
NUMERIC_KEYS: set[str] = {
    "value", "amount", "minAmount", "maxAmount", "sum", "minSum", "maxSum",
    "rate", "minRate", "maxRate", "percent", "percentage", "interest",
    "term", "minTerm", "maxTerm", "period", "minPeriod", "maxPeriod",
    "limit", "minLimit", "maxLimit", "price", "fee", "commission",
    "duration", "years", "months", "days",
}

# Units that belong to the value emitted just before them.
UNIT_KEYS: set[str] = {"currency", "unit", "measure", "suffix"}

# Date keys worth keeping, rendered with an explicit label.
DATE_KEYS: set[str] = {
    "date", "publishDate", "publishedAt", "publishedDate", "createdAt",
    "createdDate", "updatedAt", "lastUpdatedDate", "startDate", "endDate",
    "validFrom", "validTo",
}

_TOKEN_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}.*)?$")
_PUNCT_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)

MIN_UNLABELLED_PROSE = 25  # chars, for values arriving without a usable key
MIN_SECTION_PROSE = 40     # chars of real content before a section is indexed


def strip_html(value: str) -> str:
    value = html.unescape(value)
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


def normalize_whitespace(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _is_noise_string(text: str, key: str | None) -> bool:
    """True when the string is a config token, slug, bare date or punctuation."""
    if not text:
        return True
    if _PUNCT_ONLY_RE.match(text):
        return True
    if text.lower() in {"null", "none", "true", "false", "nan", "-"}:
        return True
    if key in LABELLED_KEYS:
        return False
    # "telegram", "news", "center", "text", "date", "next-news-item", ...
    if _TOKEN_RE.match(text) and len(text) <= 32:
        return True
    if _ISO_DATE_RE.match(text):
        return True
    return False


def _label_for(key: str) -> str:
    """camelCase -> spaced, capitalised label."""
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", key).replace("_", " ")
    return spaced[:1].upper() + spaced[1:].lower()


def _flatten_content(
    value: Any,
    lines: list[str],
    depth: int,
    key: str | None = None,
) -> None:
    if depth > 8:
        return

    if isinstance(value, dict):
        for child_key, child_value in value.items():
            if child_key in DROP_KEYS:
                continue
            _flatten_content(child_value, lines, depth + 1, child_key)
        return

    if isinstance(value, list):
        for item in value:
            _flatten_content(item, lines, depth + 1, key)
        return

    if isinstance(value, bool):
        return

    if isinstance(value, (int, float)):
        # Only numbers attached to a meaningful key survive; ids and counters die.
        if key in NUMERIC_KEYS:
            lines.append(f"{_label_for(key)}: {value}")
        return

    if not isinstance(value, str):
        return

    text = normalize_whitespace(strip_html(value))

    if key in DATE_KEYS:
        if text:
            lines.append(f"{_label_for(key)}: {text[:10]}")
        return

    if key in UNIT_KEYS:
        # "Amount: 50000" + "UZS" -> "Amount: 50000 UZS"
        if text and lines:
            lines[-1] = f"{lines[-1]} {text}"
        return

    if _is_noise_string(text, key):
        return

    if key in LABELLED_KEYS or key in NUMERIC_KEYS:
        lines.append(f"{_label_for(key)}: {text}")
        return

    # Unknown key: keep it only if it actually looks like prose.
    if len(text) >= MIN_UNLABELLED_PROSE and " " in text:
        lines.append(text)


def _dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        fingerprint = line.strip().lower()
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append(line)
    return out


def _prose_length(lines: list[str]) -> int:
    """Length of content excluding the Page/Breadcrumb/Section header lines."""
    return sum(
        len(line)
        for line in lines
        if not line.startswith(("Page:", "Breadcrumb:", "Section:"))
    )


def extract_page_sections(
    page: dict[str, Any],
) -> tuple[list[str], str | None, str]:
    """Return (sections, page_title, header).

    `header` is the Page/Breadcrumb prefix, returned separately so the caller
    can stamp it onto every chunk instead of once per section.
    """
    data = page.get("data") or {}

    if not isinstance(data, dict):
        return [], None, ""

    title: str | None = None
    seo = data.get("seo")
    if isinstance(seo, dict) and isinstance(seo.get("title"), str):
        title = strip_html(seo["title"])

    header_lines: list[str] = []

    code = data.get("code")
    if code:
        header_lines.append(f"Page: {code}")

    breadcrumb = data.get("breadCrumb")
    if isinstance(breadcrumb, list):
        crumbs = [
            strip_html(item["title"])
            for item in breadcrumb
            if isinstance(item, dict) and isinstance(item.get("title"), str)
        ]
        if crumbs:
            header_lines.append(f"Breadcrumb: {' > '.join(crumbs)}")

    for date_key in ("publishDate", "publishedAt", "date", "lastUpdatedDate"):
        raw_date = data.get(date_key)
        if isinstance(raw_date, str) and raw_date.strip():
            header_lines.append(f"Date: {raw_date.strip()[:10]}")
            break

    header = "\n".join(header_lines)

    raw_sections = data.get("sections")
    if not isinstance(raw_sections, list):
        return [], title, header

    sections: list[str] = []

    for section in raw_sections:
        if not isinstance(section, dict):
            continue

        section_lines: list[str] = []

        section_title = section.get("title")
        if section_title:
            section_lines.append(f"Section: {strip_html(str(section_title))}")

        blocks = section.get("blocks", [])
        if not isinstance(blocks, list):
            continue

        for block in blocks:
            if not isinstance(block, dict):
                continue

            block_type = str(block.get("type") or "").strip().lower()

            if block_type in SKIP_BLOCK_TYPES:
                continue
            if SKIP_MEDIA_BLOCKS and block_type in MEDIA_BLOCK_TYPES:
                continue

            block_lines: list[str] = []
            content = block.get("content")
            if content is not None:
                _flatten_content(content, block_lines, depth=0)

            block_lines = _dedupe(block_lines)
            if block_lines:
                section_lines.extend(block_lines)

        section_lines = _dedupe(section_lines)

        if _prose_length(section_lines) < MIN_SECTION_PROSE:
            continue

        text = normalize_whitespace("\n".join(section_lines))
        if text:
            sections.append(text)

    return sections, title, header


def extract_page_text(page: dict[str, Any]) -> tuple[str, str | None]:
    """Kept for hashing / debugging. Header appears once, not per section."""
    sections, title, header = extract_page_sections(page)
    parts = ([header] if header else []) + sections
    return normalize_whitespace("\n\n".join(parts)), title


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
    for previous, nxt in zip(chunks, chunks[1:]):
        tail = previous[-overlap:]
        adjusted.append(f"{tail}\n{nxt}")
    return adjusted


def chunk_sections(
    sections: list[str],
    size: int,
    overlap: int,
    header: str = "",
) -> list[str]:
    """Chunk per section and stamp the page header onto every chunk."""
    prefix = f"{header}\n" if header else ""
    budget = max(size - len(prefix), 200)

    chunks: list[str] = []
    for section in sections:
        for chunk in chunk_text(section, size=budget, overlap=overlap):
            chunks.append(f"{prefix}{chunk}")
    return chunks