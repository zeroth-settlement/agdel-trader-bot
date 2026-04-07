"""Lightweight JSONL persistence for trade_history and purchase_log."""

from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path

logger = logging.getLogger("persistence")

DATA_DIR = Path("data")


def append_jsonl(path: Path, record: dict):
    """Append a single JSON line to a file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        logger.error("Failed to append to %s: %s", path, e)


def rewrite_jsonl(path: Path, records: list[dict]):
    """Atomically rewrite a JSONL file with current records."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".jsonl.tmp")
        with open(tmp, "w") as f:
            for r in records:
                f.write(json.dumps(r, default=str) + "\n")
        tmp.replace(path)
    except Exception as e:
        logger.error("Failed to rewrite %s: %s", path, e)


def load_jsonl(path: Path, maxlen: int = 200) -> deque[dict]:
    """Load a JSONL file into a deque. Returns empty deque if file missing."""
    loaded = []
    if not path.exists():
        return deque(maxlen=maxlen)
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    loaded.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping corrupt line in %s", path)
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
    return deque(loaded, maxlen=maxlen)
