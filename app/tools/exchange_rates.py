"""Fetch Agrobank's live exchange rates without using the vector index."""

from __future__ import annotations

import logging
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger("agrobank.exchange_rates")

RATE_CHANNELS = {
    "office": "Exchange office",
    "atm": "ATM",
    "international": "International money transfer",
}


def _quote(value: Any) -> str:
    """A zero or missing API value is not an available transaction quote."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "not published"
    if not amount.is_finite() or amount <= 0:
        return "not published"
    return f"{format(amount, 'f')} UZS"


def parse_exchange_rates(payload: dict[str, Any], language: str) -> list[dict]:
    """Convert the three tabbed rate tables into source-backed LLM context."""
    if payload.get("success") is not True:
        raise RuntimeError("Agrobank's exchange-rates API did not return a successful response.")

    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        raise RuntimeError("Agrobank's exchange-rates API returned an unexpected structure.")

    page_url = f"https://agrobank.uz/{language}/person/exchange_rates"
    context: list[dict] = []
    for section in data["sections"]:
        if not isinstance(section, dict) or not isinstance(section.get("blocks"), list):
            continue

        channel: str | None = None
        for block in section["blocks"]:
            if not isinstance(block, dict):
                continue
            content = block.get("content")
            if not isinstance(content, dict):
                continue

            if block.get("type") == "tab":
                code = content.get("code")
                channel = code if code in RATE_CHANNELS else None
                continue
            if block.get("type") != "currency-rates" or channel is None:
                continue

            items = content.get("items")
            if not isinstance(items, list):
                continue
            lines = [
                f"Agrobank {RATE_CHANNELS[channel]} exchange rates, UZS per 1 unit of currency.",
                "Buy means Agrobank buys the foreign currency; sell means Agrobank sells it. "
                "CB is the Central Bank reference rate, not an exchange quote. "
                "A quote marked 'not published' must not be described as free or zero-cost.",
            ]
            for item in items:
                if not isinstance(item, dict):
                    continue
                currency = item.get("alpha3")
                if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
                    continue
                updated = item.get("updated")
                timestamp = f"; updated {updated}" if isinstance(updated, str) and updated else ""
                lines.append(
                    f"{currency}: buy {_quote(item.get('buy'))}; "
                    f"sell {_quote(item.get('sale'))}; "
                    f"CB {_quote(item.get('rate'))}{timestamp}."
                )

            if len(lines) > 2:
                context.append({
                    "title": f"Live Agrobank rates — {RATE_CHANNELS[channel]}",
                    "page_url": page_url,
                    "score": 1.0,
                    "text": "\n".join(lines),
                })
            channel = None  # Ignore the following duplicate calculator block.

    if not context:
        raise RuntimeError("Agrobank's exchange-rates API returned no usable rates.")
    return context


def get_exchange_rate_context(language: str) -> list[dict]:
    """Fetch a fresh public API response for every exchange-rate question."""
    started = time.monotonic()
    try:
        response = httpx.get(
            settings.bank_api_url,
            params={"action": "pages", "code": "uz/person/exchange_rates"},
            timeout=httpx.Timeout(8.0, connect=4.0),
            headers={"User-Agent": "AgrobankRAGBot/0.1 (+exchange-rates)"},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("exchange_rates.fetch_failed error=%s", type(exc).__name__)
        raise RuntimeError("Live Agrobank exchange rates are temporarily unavailable.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Agrobank's exchange-rates API returned an unexpected response.")
    context = parse_exchange_rates(payload, language)
    logger.info(
        "exchange_rates.fetched channels=%d duration_ms=%.1f",
        len(context),
        (time.monotonic() - started) * 1000,
    )
    return context
