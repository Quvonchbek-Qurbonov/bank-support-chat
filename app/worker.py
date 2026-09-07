import time

from app.core.config import get_settings
from app.db import init_db
from app.ingestion.sync_service import SyncService


def main() -> None:
    settings = get_settings()
    init_db()

    service = SyncService()
    try:
        while True:
            try:
                stats = service.sync()
                print(f"sync completed: {stats}", flush=True)
            except Exception as exc:
                print(f"sync failed: {exc!r}", flush=True)
            time.sleep(settings.sync_interval_seconds)
    finally:
        service.close()


if __name__ == "__main__":
    main()
