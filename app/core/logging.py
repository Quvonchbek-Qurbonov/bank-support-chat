from __future__ import annotations

import logging
import sys
import time
from contextvars import ContextVar, Token

from transformers.utils.logging import disable_progress_bar

from app.core.config import settings


_request_id: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestContext(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def configure_logging() -> None:
    """Configure application logs once without changing third-party loggers."""
    disable_progress_bar()
    logger = logging.getLogger("agrobank")
    logger.setLevel(getattr(logging, settings.log_level))
    logger.propagate = False

    if any(getattr(handler, "_agrobank_handler", False) for handler in logger.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler._agrobank_handler = True
    handler.addFilter(_RequestContext())
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def bind_request_id(request_id: str) -> Token[str]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)
