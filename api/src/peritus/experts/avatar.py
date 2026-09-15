"""The expert's picture avatar: what may be stored, and what to render by default.

An expert's identity is generated, not uploaded. There is no image column and no
object store: the avatar is a *recipe* — a generator name and a seed — and the
client draws it. That keeps identity free (no storage, no CDN, no moderation
problem: a user cannot upload a picture at all) while still being something the
owner can change.

There are no per-expert colours. ``hue`` survives in the stored shape only so
older clients keep parsing it, and is always null.

Two rules shape the vocabulary below.

**No face styles.** A generated human face beside "Dr. Elena Vasquez" reads as a
claim that a real person exists and wrote this. The persona is a voice the
corpus speaks with, so every style here is abstract or a monogram, and the
allowlist is enforced server-side rather than left to the client to respect.

**NULL means derived.** An expert with no stored avatar is drawn from its
persona name, deterministically, which is what every expert built before this
existed already looks like. Choosing an avatar writes the recipe and pins it —
which also fixes the older annoyance that a rebuild wrote a new persona name and
silently changed an expert's monogram in the rail.

**Since migration 027, "derived" has two levels.** An expert with no recipe now
falls to its *found picture* first — a real, licensed image of its subject,
found on Wikimedia during the build — and only to the monogram when it has
none. Nothing here changed to allow that: the build writes to
``expert_pictures``, never to this column, so a non-null value is still a choice
a person made and is still authoritative over everything else.

    avatar (chosen) -> expert_pictures (found) -> monogram (derived)
"""

from typing import Any

# Generator names the web client can draw. `sigil` is the built-in monogram
# (initials on a tinted rounded square); the rest are DiceBear collections that
# produce abstract pictures. Adding a style means adding it here *and* teaching
# the client to render it — an unknown style reaching a client that cannot draw
# it falls back to the monogram rather than rendering nothing.
AVATAR_STYLES: frozenset[str] = frozenset(
    {
        "sigil",      # monogram on a tinted rounded square (the default look)
        "shapes",     # overlapping geometric shapes
        "glass",      # soft translucent blobs
        "rings",      # concentric arcs
        "identicon",  # symmetric tile grid
        "icons",      # a single line mark
        # Renders the found picture (migration 027) rather than a generated
        # drawing, so an owner who pinned a drawing can choose the picture
        # again. A `picture` recipe on an expert that has no picture row
        # degrades to the monogram, exactly like an unknown style does.
        "picture",
    }
)

# Deliberately absent, and not an oversight: every DiceBear collection that
# draws eyes and a mouth. `thumbs` looks abstract in a thumbnail but is a face
# generator — it has `eyes` and `mouth` options — and `avataaars`, `lorelei`,
# `personas`, `micah`, `openPeeps`, `notionists`, `bottts` and friends are
# plainly faces. See the module docstring for why that matters here.

SEED_MAX_CHARS = 120


class InvalidAvatar(ValueError):
    """The recipe is not one this server will store. Message is user-facing."""


def normalise(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate and shrink an avatar recipe to exactly the three known keys.

    Returning ``None`` for a falsy input is how "reset to the generated default"
    is expressed: the caller writes NULL and the client derives again.

    Unknown keys are dropped rather than rejected. The column is a rendering
    recipe, and a client that sends a field a newer version of itself
    understands should not get a 400 from an older server — but neither should
    that field be persisted, because nothing here can validate it.
    """
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise InvalidAvatar("Avatar must be an object.")

    style = raw.get("style")
    if not isinstance(style, str) or style not in AVATAR_STYLES:
        raise InvalidAvatar(
            f"Unknown avatar style {style!r}. Choose one of: {', '.join(sorted(AVATAR_STYLES))}."
        )

    seed = raw.get("seed")
    if seed is not None:
        if not isinstance(seed, str):
            raise InvalidAvatar("Avatar seed must be a string.")
        seed = seed.strip()[:SEED_MAX_CHARS] or None

    # There are no per-expert colours. A hue from an older client is dropped,
    # not refused, and the key stays (always null) so older readers still parse.
    return {"style": style, "seed": seed, "hue": None}


def default_seed(expert) -> str:
    """What a derived avatar is seeded with: the persona name, else the slug.

    The slug fallback matters — a queued or failed expert has no persona yet, and
    seeding on the topic string would give two experts on the same topic the same
    picture.
    """
    return (expert.persona_name or "").strip() or expert.name
