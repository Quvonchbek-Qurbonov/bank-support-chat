"""Enumerate the block types and content keys actually present in raw_json.

Run this before extending SKIP_BLOCK_TYPES / DROP_KEYS so the lists match the
real Agrobank payloads instead of guesses.

    docker compose exec api python -m scripts.inspect_blocks
    docker compose exec api python -m scripts.inspect_blocks --block next-news-item
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from sqlalchemy import select

from app.db import Resource, SessionLocal
from app.ingestion.normalizer import SKIP_BLOCK_TYPES, MEDIA_BLOCK_TYPES


def iter_blocks(raw_json: dict):
    data = (raw_json or {}).get("data") or {}
    for section in data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for block in section.get("blocks") or []:
            if isinstance(block, dict):
                yield block


def collect_keys(value, out: Counter, depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            out[k] += 1
            collect_keys(v, out, depth + 1)
    elif isinstance(value, list):
        for item in value:
            collect_keys(item, out, depth + 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", help="dump one sample of this block type")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        query = select(Resource).where(Resource.is_active.is_(True))
        if args.limit:
            query = query.limit(args.limit)
        resources = session.scalars(query).all()
    finally:
        session.close()

    types: Counter = Counter()
    keys_by_type: dict[str, Counter] = {}
    sample: dict | None = None

    for resource in resources:
        for block in iter_blocks(resource.raw_json):
            block_type = str(block.get("type") or "<none>").lower()
            types[block_type] += 1
            keys_by_type.setdefault(block_type, Counter())
            collect_keys(block.get("content"), keys_by_type[block_type])
            if args.block and block_type == args.block and sample is None:
                sample = block

    print(f"resources={len(resources)} distinct_block_types={len(types)}\n")
    print(f"{'count':>7}  {'skipped':>7}  block type")
    for block_type, count in types.most_common():
        skipped = block_type in SKIP_BLOCK_TYPES or block_type in MEDIA_BLOCK_TYPES
        print(f"{count:>7}  {'YES' if skipped else '':>7}  {block_type}")

    if args.block:
        print(f"\n--- keys inside '{args.block}' ---")
        for key, count in keys_by_type.get(args.block, Counter()).most_common():
            print(f"{count:>7}  {key}")
        if sample is not None:
            print(f"\n--- sample block ---\n{json.dumps(sample, ensure_ascii=False, indent=2)[:4000]}")


if __name__ == "__main__":
    main()