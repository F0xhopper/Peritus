"""Run all .sql migration files in order against DATABASE_URL.

    python migrations/apply.py            # apply everything pending
    python migrations/apply.py --status   # list applied and pending, change nothing

This is Fly's release command, so it runs on every API deploy, before any
machine is updated. A failure here aborts the release.
"""

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

# An arbitrary but fixed key for pg_advisory_lock. Two concurrent runners would
# each see the same pending list, and both would apply it: the `IF NOT EXISTS`
# files survive that, the first plain `ALTER TABLE` anyone adds does not. Fly
# runs one release command at a time, so this is insurance rather than a fix for
# an observed race — but it costs one round trip and removes the whole class.
_LOCK_KEY = 0x50455249  # "PERI"


def _sql_files() -> list[Path]:
    return sorted(Path(__file__).parent.glob("*.sql"))


async def _connect() -> asyncpg.Connection:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")
    ssl = "require" if os.getenv("DATABASE_SSL", "false").lower() == "true" else None
    return await asyncpg.connect(url, ssl=ssl, statement_cache_size=0)


async def _ensure_table(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


async def _applied(conn: asyncpg.Connection) -> dict[str, object]:
    rows = await conn.fetch("SELECT filename, applied_at FROM _migrations")
    return {r["filename"]: r["applied_at"] for r in rows}


async def status(conn: asyncpg.Connection) -> None:
    """Print what has run and what would run next. Changes nothing."""
    await _ensure_table(conn)
    applied = await _applied(conn)
    pending = [f.name for f in _sql_files() if f.name not in applied]

    for f in _sql_files():
        when = applied.get(f.name)
        print(
            f"  {'applied' if when else 'PENDING'}  {f.name}"
            + (f"  {when:%Y-%m-%d %H:%M}" if when else "")
        )

    orphans = sorted(set(applied) - {f.name for f in _sql_files()})
    if orphans:
        # Recorded as applied but no longer on disk: someone deleted or renamed
        # a migration, which means this database and the tree disagree.
        print(f"\n  {len(orphans)} recorded migration(s) missing from disk: {', '.join(orphans)}")

    print(f"\n{len(applied)} applied, {len(pending)} pending.")


async def apply(conn: asyncpg.Connection) -> None:
    await _ensure_table(conn)
    applied = await _applied(conn)

    for f in _sql_files():
        if f.name in applied:
            print(f"  skip  {f.name}")
            continue
        print(f"  apply {f.name}…")
        sql = f.read_text()
        # Applying the file and recording that it was applied are one unit.
        # Split across two statements, a crash between them leaves a
        # migration applied but unrecorded, so the next run re-applies it —
        # fine for the `IF NOT EXISTS` files here, silently fatal for the
        # first non-idempotent `ALTER TABLE` anyone adds.
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute("INSERT INTO _migrations (filename) VALUES ($1)", f.name)
        print(f"  done  {f.name}")

    print("All migrations applied.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--status",
        action="store_true",
        help="list applied and pending migrations without applying anything",
    )
    args = parser.parse_args()

    conn = await _connect()
    try:
        if args.status:
            await status(conn)
            return
        # Session-scoped: held until this connection closes, which is the
        # `finally` below.
        await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_KEY)
        try:
            await apply(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
