"""Dump the API's OpenAPI schema to stdout.

    python scripts/openapi.py > openapi.json

From the app object, not from a running server: the schema is a pure function
of the route signatures and the Pydantic models, so generating it needs no
database, no Supabase project and no network — which is what lets CI check it
on every run.

`just types` feeds this to `openapi-typescript` to produce
`web/lib/api/generated.ts`, and the web job fails if the committed file and a
fresh generation disagree. That is the only automatic link between a renamed
Python field and the TypeScript that reads it.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# The app refuses to start without these. Nothing here connects to anything —
# the schema is built from the route table — so placeholders are honest.
os.environ.setdefault("DATABASE_URL", "postgresql://schema:schema@localhost/schema")
os.environ.setdefault("OPENAI_API_KEY", "schema")
os.environ.setdefault("ANTHROPIC_API_KEY", "schema")

from peritus.api.app import create_app


def main() -> None:
    schema = create_app().openapi()
    # `sort_keys` and a trailing newline so the file is byte-stable and a diff
    # shows what changed rather than a reordering.
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
