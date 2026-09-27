import io
import logging
import unittest

import httpx
from transformers.utils.logging import is_progress_bar_enabled

from app.core.logging import bind_request_id, configure_logging, reset_request_id
from app.ingestion.sync_service import _log_fetch_failure


class LoggingTests(unittest.TestCase):
    def test_expected_page_404_is_debug_and_single_line(self):
        request = httpx.Request("GET", "https://agrobank.uz/api/v1/?secret=hidden")
        error = httpx.HTTPStatusError(
            "multi-line\nerror", request=request, response=httpx.Response(404, request=request),
        )

        with self.assertLogs("agrobank.sync", level="DEBUG") as logs:
            _log_fetch_failure("en/missing", error)

        self.assertEqual(logs.records[0].levelno, logging.DEBUG)
        self.assertIn("status=404", logs.output[0])
        self.assertNotIn("secret", logs.output[0])
        self.assertNotIn("\n", logs.output[0])

    def test_configuration_is_idempotent_and_includes_request_id(self):
        logger = logging.getLogger("agrobank")
        original_handlers = list(logger.handlers)
        original_level = logger.level
        original_propagate = logger.propagate
        try:
            configure_logging()
            handlers = [handler for handler in logger.handlers if getattr(handler, "_agrobank_handler", False)]
            configure_logging()
            self.assertFalse(is_progress_bar_enabled())
            self.assertEqual(len(handlers), 1)
            self.assertEqual(logger.handlers.count(handlers[0]), 1)

            stream = io.StringIO()
            handler = handlers[0]
            original_stream = handler.stream
            token = bind_request_id("test-request")
            try:
                handler.stream = stream
                logging.getLogger("agrobank.test").info("test.event count=3")
            finally:
                reset_request_id(token)
                handler.stream = original_stream

            line = stream.getvalue()
            self.assertIn("request_id=test-request", line)
            self.assertIn("test.event count=3", line)
        finally:
            for handler in list(logger.handlers):
                if handler not in original_handlers:
                    logger.removeHandler(handler)
                    handler.close()
            logger.setLevel(original_level)
            logger.propagate = original_propagate


if __name__ == "__main__":
    unittest.main()
