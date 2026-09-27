from __future__ import annotations

import logging
import time
import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import init_db
from app.ingestion.sync_service import SyncService


logger = logging.getLogger("agrobank.worker")


async def main() -> None:
    configure_logging()
    settings = get_settings()

    init_db()

    logger.info(
        "worker.started interval_s=%s http_concurrency=%s embedding_device=%s "
        "embedding_batch_size=%s",
        settings.sync_interval_seconds,
        settings.sync_http_concurrency,
        settings.embedding_device,
        settings.embedding_batch_size,
    )

    service = SyncService()

    sync_id = 0

    try:
        while True:
            sync_id += 1
            started = time.monotonic()

            logger.info("sync.started sync_id=%s", sync_id)

            try:
                stats = await service.sync()

                logger.info(
                    "sync.completed sync_id=%s "
                    "discovered=%s fetched=%s new=%s "
                    "updated=%s unchanged=%s failed=%s "
                    "embedded=%s chunks=%s deactivated=%s "
                    "duration_s=%.2f",
                    sync_id,
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

            except Exception:
                logger.exception("sync.failed sync_id=%s", sync_id)

            elapsed = time.monotonic() - started

            logger.debug(
                "sync.sleep interval_s=%s iteration_s=%.2f",
                settings.sync_interval_seconds,
                elapsed,
            )

            await asyncio.sleep(
                settings.sync_interval_seconds
            )

    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(main())
