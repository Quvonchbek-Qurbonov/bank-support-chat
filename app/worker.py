from __future__ import annotations

import logging
import time

from app.core.config import get_settings
from app.db import init_db
from app.ingestion.sync_service import SyncService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("agrobank.worker")


def main() -> None:
    settings = get_settings()

    init_db()

    logger.info(
        "Worker started | interval=%ss | "
        "http_concurrency=%s | embedding_device=%s | "
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

            logger.info(
                "===== SYNC #%s START =====",
                sync_id,
            )

            try:
                stats = service.sync()

                logger.info(
                    "===== SYNC #%s FINISHED =====",
                    sync_id,
                )

                logger.info(
                    "Sync #%s | "
                    "discovered=%s fetched=%s new=%s "
                    "updated=%s unchanged=%s failed=%s "
                    "embedded=%s chunks=%s deactivated=%s "
                    "duration=%.2fs",
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
                logger.exception(
                    "SYNC #%s FAILED",
                    sync_id,
                )

            elapsed = time.monotonic() - started

            logger.info(
                "Next sync in %ss | "
                "current iteration took %.2fs",
                settings.sync_interval_seconds,
                elapsed,
            )

            time.sleep(
                settings.sync_interval_seconds
            )

    finally:
        service.close()


if __name__ == "__main__":
    main()