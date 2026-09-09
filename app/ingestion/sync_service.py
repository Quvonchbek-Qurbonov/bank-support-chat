from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.db import Resource, SessionLocal
from app.ingestion.bank_client import AgrobankClient
from app.ingestion.discovery import (
    ReferenceExtractor,
    menu_page_codes,
)
from app.ingestion.normalizer import (
    chunk_text,
    extract_page_text,
)
from app.rag.embeddings import EmbeddingService
from app.rag.vector_store import VectorStore


logger = logging.getLogger("agrobank.sync")


class SyncService:
    def __init__(self) -> None:
        self.settings = get_settings()

        self.client = AgrobankClient()
        self.extractor = ReferenceExtractor()
        self.embedder = EmbeddingService()
        self.vector_store = VectorStore()

        self.http_semaphore = asyncio.Semaphore(
            self.settings.sync_http_concurrency
        )

    def close(self) -> None:
        asyncio.run(self.client.close())

    def sync(self) -> dict[str, Any]:
        return asyncio.run(self._sync_async())

    async def _sync_async(self) -> dict[str, Any]:
        started = time.monotonic()

        stats: dict[str, Any] = {
            "discovered": 0,
            "fetched": 0,
            "new": 0,
            "updated": 0,
            "unchanged": 0,
            "embedded": 0,
            "chunks": 0,
            "failed": 0,
            "deactivated": 0,
        }

        logger.info("Starting Agrobank synchronization")

        menu = await self.client.get_menu()

        queue: deque[tuple[str, str | None]] = deque()
        queued: set[str] = set()

        for language in self.settings.languages:
            for code in menu_page_codes(
                menu,
                language,
            ):
                queue.append((code, None))
                queued.add(code)

        visited: set[str] = set()

        stats["discovered"] = len(queue)

        logger.info(
            "Initial pages discovered=%s",
            len(queue),
        )

        # Process discovery in waves.
        #
        # Each wave fetches multiple pages concurrently.
        # Newly discovered child pages are added to the next wave.
        while queue:
            batch: list[tuple[str, str | None]] = []

            while queue and len(batch) < self.settings.sync_http_concurrency:
                code, discovered_from = queue.popleft()

                if code in visited:
                    continue

                visited.add(code)
                batch.append((code, discovered_from))

            if not batch:
                continue

            logger.info(
                "Fetching batch | size=%s | progress=%s/%s",
                len(batch),
                len(visited),
                stats["discovered"],
            )

            results = await asyncio.gather(
                *[
                    self._fetch_page(
                        code,
                        language=code.split("/", 1)[0],
                        discovered_from=discovered_from,
                    )
                    for code, discovered_from in batch
                ],
                return_exceptions=True,
            )

            changed_pages: list[dict[str, Any]] = []

            for (code, discovered_from), result in zip(
                batch,
                results,
            ):
                if isinstance(result, Exception):
                    stats["failed"] += 1

                    logger.error(
                        "Failed fetching page | code=%s | error=%r",
                        code,
                        result,
                    )

                    continue

                stats["fetched"] += 1

                status = result["status"]

                if status == "new":
                    stats["new"] += 1
                elif status == "updated":
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1

                for child_code in result["children"]:
                    if (
                        child_code not in visited
                        and child_code not in queued
                    ):
                        queue.append(
                            (
                                child_code,
                                code,
                            )
                        )
                        queued.add(child_code)
                        stats["discovered"] += 1

                if status in {"new", "updated"}:
                    changed_pages.append(result)

                logger.info(
                    "Page processed | status=%s | code=%s",
                    status,
                    code,
                )

            if changed_pages:
                embedding_stats = self._embed_and_persist(
                    changed_pages
                )

                stats["embedded"] += embedding_stats["embedded"]
                stats["chunks"] += embedding_stats["chunks"]

        stats["deactivated"] = self._mark_missing_resources(
            visited
        )

        stats["duration_seconds"] = round(
            time.monotonic() - started,
            2,
        )

        logger.info(
            "Sync finished | "
            "discovered=%s fetched=%s new=%s updated=%s "
            "unchanged=%s failed=%s embedded=%s chunks=%s "
            "deactivated=%s duration=%.2fs",
            stats["discovered"],
            stats["fetched"],
            stats["new"],
            stats["updated"],
            stats["unchanged"],
            stats["failed"],
            stats["embedded"],
            stats["chunks"],
            stats["deactivated"],
            stats["duration_seconds"],
        )

        return stats

    async def _fetch_page(
        self,
        code: str,
        language: str,
        discovered_from: str | None,
    ) -> dict[str, Any]:
        async with self.http_semaphore:
            started = time.monotonic()

            payload = await self.client.get_page(code)

            page_text, title = extract_page_text(
                payload
            )

            content_hash = hashlib.sha256(
                page_text.encode("utf-8")
            ).hexdigest()

            chunks = chunk_text(
                page_text,
                self.settings.chunk_size,
                self.settings.chunk_overlap,
            )

            children = self.extractor.extract_page_codes(
                payload,
                language,
            )

            children.discard(code)

            status = self._get_page_status(
                code,
                content_hash,
            )

            elapsed = time.monotonic() - started

            logger.debug(
                "Fetched page | code=%s | status=%s | "
                "chunks=%s | children=%s | %.2fs",
                code,
                status,
                len(chunks),
                len(children),
                elapsed,
            )

            return {
                "code": code,
                "language": language,
                "discovered_from": discovered_from,
                "payload": payload,
                "page_text": page_text,
                "title": title,
                "content_hash": content_hash,
                "chunks": chunks,
                "children": children,
                "status": status,
            }

    def _get_page_status(
        self,
        code: str,
        content_hash: str,
    ) -> str:
        session = SessionLocal()

        try:
            resource = session.scalar(
                select(Resource).where(
                    Resource.code == code
                )
            )

            if resource is None:
                return "new"

            if resource.content_hash != content_hash:
                return "updated"

            return "unchanged"

        finally:
            session.close()

    def _embed_and_persist(
        self,
        pages: list[dict[str, Any]],
    ) -> dict[str, int]:
        all_chunks: list[str] = []

        for page in pages:
            all_chunks.extend(page["chunks"])

        if not all_chunks:
            return {
                "embedded": 0,
                "chunks": 0,
            }

        started = time.monotonic()

        logger.info(
            "Embedding changed pages=%s chunks=%s",
            len(pages),
            len(all_chunks),
        )

        all_embeddings = self.embedder.embed_documents(
            all_chunks
        )

        logger.info(
            "Embedding finished | chunks=%s | duration=%.2fs",
            len(all_chunks),
            time.monotonic() - started,
        )

        embedding_index = 0

        embedded_pages = 0

        for page in pages:
            chunks = page["chunks"]

            page_embeddings = all_embeddings[
                embedding_index:
                embedding_index + len(chunks)
            ]

            embedding_index += len(chunks)

            self._persist_page(
                page,
                page_embeddings,
            )

            embedded_pages += 1

        return {
            "embedded": embedded_pages,
            "chunks": len(all_chunks),
        }

    def _persist_page(
        self,
        page: dict[str, Any],
        embeddings: list[list[float]],
    ) -> None:
        code = page["code"]
        language = page["language"]
        payload = page["payload"]
        page_text = page["page_text"]
        title = page["title"]
        content_hash = page["content_hash"]
        discovered_from = page["discovered_from"]
        chunks = page["chunks"]

        source_updated_at = (
            payload.get("data") or {}
        ).get("lastUpdatedDate")

        page_url = (
            f"{self.settings.bank_base_url}/{code}"
        )

        api_url = (
            f"{self.settings.bank_api_url}"
            f"?action=pages&code={code}"
        )

        now = datetime.now(timezone.utc)

        session = SessionLocal()

        try:
            resource = session.scalar(
                select(Resource).where(
                    Resource.code == code
                )
            )

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

            else:
                resource.language = language
                resource.page_url = page_url
                resource.api_url = api_url
                resource.title = title
                resource.last_seen_at = now
                resource.is_active = True
                resource.discovered_from = (
                    resource.discovered_from
                    or discovered_from
                )

                resource.content_text = page_text
                resource.raw_json = payload
                resource.content_hash = content_hash
                resource.source_updated_at = (
                    source_updated_at
                )

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

        except Exception:
            session.rollback()
            raise

        finally:
            session.close()

    def _mark_missing_resources(
        self,
        seen_codes: set[str],
    ) -> int:
        session = SessionLocal()
        deactivated = 0

        try:
            resources = session.scalars(
                select(Resource)
            ).all()

            for resource in resources:
                if resource.code not in seen_codes:
                    self.vector_store.delete_resource_chunks(
                        resource.id
                    )

                    if resource.is_active:
                        resource.is_active = False
                        deactivated += 1

            session.commit()

        finally:
            session.close()

        return deactivated