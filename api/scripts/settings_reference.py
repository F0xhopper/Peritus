"""Print every setting, its type and its default, as a Markdown table.

    just settings

`docs/configuration.md` deliberately does not embed this: a table copied into a
document is a table that rots, and `.env.example` already carries the prose for
each setting — `tests/unit/test_env_example.py` fails if the two disagree. This
is for the moments when you want the whole list at a glance, or want to paste a
current one into an issue.
"""

import sys
from pathlib import Path
from typing import Literal, get_args, get_origin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from peritus.core.config import Settings


def _render_type(annotation: object) -> str:
    if get_origin(annotation) is Literal:
        return " \\| ".join(f"`{a}`" for a in get_args(annotation))
    return f"`{getattr(annotation, '__name__', annotation)}`"


def _render_default(value: object) -> str:
    if value is None or value == "":
        return "*(unset)*"
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    return f"`{value}`"


def main() -> None:
    print("| Setting | Type | Default |")
    print("|---|---|---|")
    for name, field in Settings.model_fields.items():
        print(f"| `{name}` | {_render_type(field.annotation)} | {_render_default(field.default)} |")

    derived = [
        n for n, v in vars(Settings).items() if isinstance(v, property) and not n.startswith("_")
    ]
    print(
        f"\nDerived (read-only, not environment variables): {', '.join(f'`{d}`' for d in derived)}"
    )


if __name__ == "__main__":
    main()
