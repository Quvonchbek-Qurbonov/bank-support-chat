from __future__ import annotations

import html
import re
from typing import Any

from bs4 import BeautifulSoup


NOISE_KEYS = {
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
}

TEXT_KEYS = {
    "title",
    "description",
    "text",
    "name",
    "buttonTitle",
    "label",
    "code",
    "currency",
}


def strip_html(value: str) -> str:
    value = html.unescape(value)
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


def normalize_whitespace(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def extract_page_text(page: dict[str, Any]) -> tuple[str, str | None]:
    data = page.get("data") or {}
    if not isinstance(data, dict):
        return "", None

    title: str | None = None
    seo = data.get("seo")
    if isinstance(seo, dict) and isinstance(seo.get("title"), str):
        title = strip_html(seo["title"])

    lines: list[str] = []

    code = data.get("code")
    if code:
        lines.append(f"Page: {code}")

    breadcrumb = data.get("breadCrumb")
    if isinstance(breadcrumb, list):
        crumbs = []
        for item in breadcrumb:
            if isinstance(item, dict) and isinstance(item.get("title"), str):
                crumbs.append(strip_html(item["title"]))
        if crumbs:
            lines.append(f"Breadcrumb: {' > '.join(crumbs)}")

    sections = data.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_title = section.get("title")
            section_code = section.get("code")
            if section_title:
                lines.append(f"Section: {strip_html(str(section_title))}")
            elif section_code:
                lines.append(f"Section: {section_code}")

            for block in section.get("blocks", []) or []:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type:
                    lines.append(f"Block: {block_type}")
                content = block.get("content")
                if content is not None:
                    _flatten_content(content, lines, depth=0)

    last_updated = data.get("lastUpdatedDate")
    if last_updated:
        lines.append(f"Source updated: {last_updated}")

    text = normalize_whitespace("\n".join(lines))
    return text, title


def _flatten_content(value: Any, lines: list[str], depth: int, key: str | None = None) -> None:
    if depth > 8:
        return

    if isinstance(value, dict):
        for k, v in value.items():
            if k in NOISE_KEYS:
                continue
            _flatten_content(v, lines, depth + 1, k)
        return

    if isinstance(value, list):
        for item in value:
            _flatten_content(item, lines, depth + 1, key)
        return

    if isinstance(value, (str, int, float, bool)):
        text = strip_html(str(value)) if isinstance(value, str) else str(value)
        if not text or text.lower() in {"null", "none"}:
            return
        if key in {"url", "path", "buttonLink", "mainPageUrl"}:
            return
        if key in TEXT_KEYS:
            prefix = key.replace("camel", "")
            lines.append(f"{prefix}: {text}")
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

    # Give subsequent chunks a little continuity without duplicating everything.
    if overlap == 0 or len(chunks) <= 1:
        return chunks

    adjusted = [chunks[0]]
    for previous, current in zip(chunks, chunks[1:]):
        tail = previous[-overlap:]
        adjusted.append(f"{tail}\n{current}")
    return adjusted
