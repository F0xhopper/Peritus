"""Run all .sql migration files in order against DATABASE_URL."""

import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set")

    ssl = "require" if os.getenv("DATABASE_SSL", "false").lower() == "true" else None
    conn = await asyncpg.connect(url, ssl=ssl, statement_cache_size=0)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    applied = {r["filename"] for r in await conn.fetch("SELECT filename FROM _migrations")}

    migrations_dir = Path(__file__).parent
    sql_files = sorted(migrations_dir.glob("*.sql"))

    try:
        for f in sql_files:
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
    finally:
        await conn.close()
    print("All migrations applied.")


if __name__ == "__main__":
    asyncio.run(main())
