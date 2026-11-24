#!/usr/bin/env python3
"""Lock-free Parquet dataset storage and stateless DuckDB query helper.

Why Parquet + in-memory DuckDB instead of a persistent .duckdb file:
1. No single-writer file lock collisions when multiple Gemini Web chats run concurrently.
2. Date-partitioned Parquet files stay small and append-friendly for GitHub backup (`wb data-sync`).
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
from typing import Any, Sequence
import uuid


def datasets_root() -> Path:
    home = Path(os.environ.get("WB_HOME", str(Path.home())))
    root = home / "data" / "datasets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_topic(topic: str) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", topic.strip().lower()).strip("-")
    if not cleaned:
        raise ValueError(f"Invalid dataset topic name: {topic!r}")
    return cleaned


def dataset_glob(topic: str) -> str:
    topic_dir = datasets_root() / sanitize_topic(topic)
    return str(topic_dir / "*.parquet")


def append_parquet(
    topic: str,
    records: Sequence[dict[str, Any]] | Any,
    dedup_keys: Sequence[str] | None = None,
    partition_date: str | None = None,
) -> Path:
    """Write or merge records into ~/data/datasets/<topic>/YYYY-MM-DD.parquet atomically.

    `records` may be a sequence of dicts, a Polars DataFrame, or a PyArrow Table.
    If `dedup_keys` is provided and today's partition already exists, existing and new rows
    are merged and deduplicated (keeping the latest row) via atomic file replacement.
    """
    import polars as pl  # type: ignore

    topic_dir = datasets_root() / sanitize_topic(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)

    day_str = partition_date or date.today().isoformat()
    if isinstance(records, pl.DataFrame):
        new_df = records
    else:
        new_df = pl.DataFrame(records)

    if new_df.is_empty():
        raise ValueError("Refusing to write an empty DataFrame to Parquet.")

    if dedup_keys:
        target = topic_dir / f"{day_str}.parquet"
        if target.exists():
            existing_df = pl.read_parquet(target)
            combined = pl.concat([existing_df, new_df], how="diagonal_relaxed")
            new_df = combined.unique(subset=list(dedup_keys), keep="last", maintain_order=True)
        else:
            new_df = new_df.unique(subset=list(dedup_keys), keep="last", maintain_order=True)
    else:
        # Without dedup_keys, avoid overwriting an existing partition file on concurrent runs
        target = topic_dir / f"{day_str}.parquet"
        if target.exists():
            target = topic_dir / f"{day_str}_{uuid.uuid4().hex[:8]}.parquet"

    tmp_file = topic_dir / f".tmp_{uuid.uuid4().hex}.parquet"
    new_df.write_parquet(tmp_file, compression="zstd")
    os.replace(tmp_file, target)
    return target


def query_parquet(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    """Execute a stateless in-memory DuckDB SQL query (working directory set to ~/data/datasets)."""
    import duckdb  # type: ignore

    root = datasets_root()
    prev_cwd = Path.cwd()
    os.chdir(root)
    try:
        con = duckdb.connect(":memory:")
        rel = con.execute(sql, params or [])
        cols = [desc[0] for desc in rel.description]
        return [dict(zip(cols, row)) for row in rel.fetchall()]
    finally:
        os.chdir(prev_cwd)


def list_topics() -> list[dict[str, Any]]:
    root = datasets_root()
    items: list[dict[str, Any]] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        files = sorted(d.glob("*.parquet"))
        total_bytes = sum(f.stat().st_size for f in files)
        items.append(
            {
                "topic": d.name,
                "parquet_files": len(files),
                "total_bytes": total_bytes,
                "glob": f"{d.name}/*.parquet",
            }
        )
    return items


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Stateless DuckDB + Parquet dataset helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("topics", help="List available Parquet dataset topics")

    q_parser = sub.add_parser(
        "query",
        help="Run SQL relative to ~/data/datasets (e.g. \"SELECT * FROM 'prices/*.parquet' LIMIT 5\")",
    )
    q_parser.add_argument("sql", help="DuckDB SQL query")

    args = parser.parse_args()
    if args.cmd == "topics":
        print(json.dumps(list_topics(), ensure_ascii=False, indent=2))
    elif args.cmd == "query":
        rows = query_parquet(args.sql)
        print(json.dumps(rows, ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
