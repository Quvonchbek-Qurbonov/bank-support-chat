from __future__ import annotations

import hashlib
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from app.core.config import get_settings
from app.db import Resource, SessionLocal
from app.ingestion.bank_client import AgrobankClient
from app.ingestion.discovery import ReferenceExtractor, menu_page_codes
from app.ingestion.normalizer import chunk_text, extract_page_text
from app.rag.embeddings import EmbeddingService
from app.rag.vector_store import VectorStore


class SyncService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = AgrobankClient()
        self.extractor = ReferenceExtractor()
        self.embedder = EmbeddingService()
        self.vector_store = VectorStore()

    def close(self) -> None:
        self.client.close()

    def sync(self) -> dict[str, int]:
        stats = {"discovered": 0, "fetched": 0, "changed": 0, "embedded": 0, "failed": 0}
        menu = self.client.get_menu()

        queue: deque[tuple[str, str | None]] = deque()
        queued: set[str] = set()

        for language in self.settings.languages:
            for code in menu_page_codes(menu, language):
                queue.append((code, None))
                queued.add(code)

        visited: set[str] = set()
        stats["discovered"] = len(queue)

        while queue:
            code, discovered_from = queue.popleft()
            if code in visited:
                continue
            visited.add(code)

            language = code.split("/", 1)[0]
            try:
                result = self._sync_page(code, language, discovered_from)
                stats["fetched"] += 1
                if result["changed"]:
                    stats["changed"] += 1
                    stats["embedded"] += 1

                for child_code in result["children"]:
                    if child_code not in visited and child_code not in queued:
                        queue.append((child_code, code))
                        queued.add(child_code)
                        stats["discovered"] += 1
            except Exception:
                stats["failed"] += 1

        self._mark_missing_resources(visited)
        return stats

    def _sync_page(self, code: str, language: str, discovered_from: str | None) -> dict[str, Any]:
        payload = self.client.get_page(code)
        page_text, title = extract_page_text(payload)
        content_hash = hashlib.sha256(page_text.encode("utf-8")).hexdigest()
        chunks = chunk_text(page_text, self.settings.chunk_size, self.settings.chunk_overlap)
        source_updated_at = (payload.get("data") or {}).get("lastUpdatedDate")

        page_url = f"{self.settings.bank_base_url}/{code}"
        api_url = f"{self.settings.bank_api_url}?action=pages&code={code}"

        changed = False
        session = SessionLocal()
        try:
            resource = session.scalar(select(Resource).where(Resource.code == code))
            now = datetime.now(timezone.utc)

            if resource is None:
                resource = Resource(
                    code=code,
                    language=language,
                    page_url=page_url,
                    api_url=api_url,
                    title=title,
                    content_text=page_text,
                    raw_json=payload,
                    content_hash=content_hash,
                    discovered_from=discovered_from,
                    source_updated_at=source_updated_at,
                    is_active=True,
                    last_seen_at=now,
                )
                session.add(resource)
                session.flush()
                changed = True
            else:
                changed = resource.content_hash != content_hash
                resource.language = language
                resource.page_url = page_url
                resource.api_url = api_url
                resource.title = title
                resource.last_seen_at = now
                resource.is_active = True
                resource.discovered_from = resource.discovered_from or discovered_from
                if changed:
                    resource.content_text = page_text
                    resource.raw_json = payload
                    resource.content_hash = content_hash
                    resource.source_updated_at = source_updated_at

            if changed:
                embeddings = self.embedder.embed_documents(chunks)
                self.vector_store.replace_resource_chunks(
                    resource_id=resource.id,
                    page_url=page_url,
                    language=language,
                    title=title,
                    chunks=chunks,
                    embeddings=embeddings,
                )
                resource.last_processed_at = now

            session.commit()
        finally:
            session.close()

        # Discover child pages regardless of whether the content changed.
        children = self.extractor.extract_page_codes(payload, language)
        children.discard(code)
        return {"changed": changed, "children": children}

    def _mark_missing_resources(self, seen_codes: set[str]) -> None:
        session = SessionLocal()

        try:
            resources = session.scalars(select(Resource)).all()

            for resource in resources:
                if resource.code not in seen_codes:
                    if resource.is_active:
                        self.vector_store.delete_resource_chunks(resource.id)
                        resource.is_active = False
                    else:
                        self.vector_store.delete_resource_chunks(resource.id)

            session.commit()
        finally:
            session.close()

