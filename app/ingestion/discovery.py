from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.core.config import get_settings


@dataclass(frozen=True)
class DiscoveredPage:
    code: str
    language: str
    source_code: str | None = None


class ReferenceExtractor:
    """Find internal Agrobank page routes inside arbitrary API JSON."""

    LINK_KEYS = {
        "path",
        "url",
        "buttonLink",
        "mainPageUrl",
    }

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_host = urlparse(self.settings.bank_base_url).netloc

    def extract_page_codes(self, payload: Any, current_language: str) -> set[str]:
        found: set[str] = set()
        self._walk(payload, current_language, found)
        return found

    def _walk(self, value: Any, language: str, found: set[str], key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                self._walk(child_value, language, found, child_key)
            return

        if isinstance(value, list):
            for child in value:
                self._walk(child, language, found, key)
            return

        if not isinstance(value, str) or key not in self.LINK_KEYS:
            return

        route = self._to_internal_route(value, language)
        if route:
            found.add(route)

    def _to_internal_route(self, raw: str, language: str) -> str | None:
        raw = raw.strip()
        if not raw or raw.startswith("#") or raw.startswith("javascript:"):
            return None

        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urlparse(raw)
            if parsed.netloc != self.base_host:
                return None
            raw = parsed.path

        if not raw.startswith("/"):
            return None

        route = raw.split("?", 1)[0].split("#", 1)[0].strip("/")
        if not route:
            return None

        lower = route.lower()
        blocked_prefixes = ("upload/", "uploads/", "static/", "assets/")
        blocked_extensions = (
            ".pdf", ".xlsx", ".xls", ".doc", ".docx", ".ppt", ".pptx",
            ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4",
        )
        if lower.startswith(blocked_prefixes) or lower.endswith(blocked_extensions):
            return None

        # API page codes always begin with a language segment.
        first = route.split("/", 1)[0]
        if first not in self.settings.languages:
            route = f"{language}/{route}"

        return route


def menu_page_codes(menu: dict[str, Any], language: str) -> set[str]:
    """Turn the nested menu tree into route codes.

    directLink entries already contain a full site path (e.g. person/cards).
    Other entries are relative to their parent menu node.
    """
    found: set[str] = set()

    language_menu = menu.get(language, {})
    for root_name in ("main", "footer"):
        for item in language_menu.get(root_name, []) or []:
            _walk_menu_item(item, language, "", found)

    return found


def _walk_menu_item(item: dict[str, Any], language: str, parent: str, found: set[str]) -> None:
    path = str(item.get("path", "")).strip()
    if not path:
        return

    external_link = str(item.get("externalLink", "")).strip()
    if external_link.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        if urlparse(external_link).netloc and urlparse(external_link).netloc != urlparse(get_settings().bank_base_url).netloc:
            return

    normalized = path.strip("/")
    already_localized = normalized == language or normalized.startswith(f"{language}/")

    direct = bool(item.get("directLink"))
    if already_localized:
        route = normalized
    elif direct:
        route = normalized
    else:
        route = "/".join(x for x in [parent.strip("/"), normalized] if x)

    if route:
        full_code = route if route.startswith(f"{language}/") else f"{language}/{route}"
        found.add(full_code)

    child_parent = route[len(language) + 1:] if route.startswith(f"{language}/") else route
    for child in item.get("children", []) or []:
        if isinstance(child, dict):
            _walk_menu_item(child, language, child_parent, found)
