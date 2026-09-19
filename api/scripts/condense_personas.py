"""Strip opening scripts from stored personas and condense them to the cap.

    python scripts/condense_personas.py --backup personas.json          # dry run
    python scripts/condense_personas.py --backup personas.json --apply  # write

One-off, for personas generated before ``PERSONA_MAX_CHARS`` existed (they ran
to 3,300–4,000 characters and several scripted how every answer opens). New
builds go through the same ``condense_persona`` inside ``generate_persona``.

Every persona is written to ``--backup`` before anything changes, so a run can
be undone by writing those back. The prompt cache re-primes once per expert.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from peritus.experts.build.persona import (
    PERSONA_MAX_CHARS,
    condense_persona,
    scripted_sentences,
)
from peritus.infrastructure.database import get_pool, init_pool


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expert", type=int, action="append", help="only these ids")
    args = parser.parse_args()

    await init_pool()
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, persona_style FROM experts WHERE persona_style IS NOT NULL ORDER BY id"
    )
    rows = [r for r in rows if not args.expert or r["id"] in args.expert]
    args.backup.write_text(json.dumps({r["id"]: r["persona_style"] for r in rows}, indent=2))
    print(f"Backed up {len(rows)} personas to {args.backup}")

    for row in rows:
        style = row["persona_style"]
        scripted = scripted_sentences(style)
        if len(style) <= PERSONA_MAX_CHARS and not scripted:
            print(f"[{row['id']}] {len(style)} chars, nothing to do")
            continue
        new = await condense_persona(style)
        print(
            f"[{row['id']}] {len(style)} → {len(new)} chars; {len(scripted)} scripting sentence(s)"
        )
        for sentence in scripted:
            print(f"    removed: {sentence[:110]}")
        if args.apply:
            await pool.execute(
                "UPDATE experts SET persona_style = $2 WHERE id = $1", row["id"], new
            )
        else:
            print("    " + new.replace("\n", "\n    "))
    if not args.apply:
        print("Dry run: nothing written. Pass --apply to write.")


if __name__ == "__main__":
    asyncio.run(main())
