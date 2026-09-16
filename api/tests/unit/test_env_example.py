"""`.env.example` is the documentation for `Settings`, so it has to stay exact.

Ten settings existed in `config.py` and nowhere else when this was written —
including `DISCOVERY_LOOP`, which decides whether a build searches more than
once, and `SCREENING_CAPTURE_DIR`, which writes whole documents to disk. Anyone
configuring a deployment from the example file had no way to know they were
there, and one documented default (`GRAPH_BATCH_SIZE`) disagreed with the code.
The drift accumulated silently because nothing compared the two.
"""

import re
from pathlib import Path

from peritus.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# `KEY=value`, with or without the leading `#` that marks an optional setting.
_ASSIGNMENT = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$", re.MULTILINE)


def _example_entries() -> dict[str, str]:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    # A trailing `# comment` on a value line is annotation, not part of the value.
    return {k: v.split("#")[0].strip() for k, v in _ASSIGNMENT.findall(text)}


def _code_default(name: str) -> str:
    default = Settings.model_fields[name].default
    if isinstance(default, bool):
        return str(default).lower()
    return "" if default is None else str(default)


def test_every_setting_appears_in_the_example():
    documented = set(_example_entries())
    missing = sorted(set(Settings.model_fields) - documented)
    assert not missing, (
        f"{len(missing)} setting(s) exist in config.py but not in .env.example: "
        f"{', '.join(missing)}. Add each with the comment that explains it."
    )


def test_the_example_invents_no_settings():
    """The other direction: a renamed field leaves a stale key behind, and a key
    that configures nothing is worse than no key at all."""
    unknown = sorted(set(_example_entries()) - set(Settings.model_fields))
    assert not unknown, (
        f".env.example documents {len(unknown)} key(s) that are not settings: {', '.join(unknown)}."
    )


def test_stated_defaults_match_the_code():
    """Where the example states a value, it must be the value the code uses.

    Settings whose code default is empty are exempt: those are the ones you must
    supply (`DATABASE_URL`, the API keys, the Supabase project), and the example
    carries a placeholder to show the shape rather than a default.
    """
    entries = _example_entries()
    disagreements = []
    for name in Settings.model_fields:
        default = _code_default(name)
        stated = entries.get(name, "")
        if default and stated and stated != default:
            disagreements.append(f"{name}: example says {stated!r}, code says {default!r}")
    assert not disagreements, "\n".join(disagreements)
