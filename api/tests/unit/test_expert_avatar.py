"""The avatar recipe normaliser.

The point of these is the allowlist. The column stores whatever the API hands
it, so if `normalise` let a face style or an unbounded seed through, the CHECK
constraint would not catch it — style vocabulary is deliberately not encoded in
SQL (migration 026), which puts the whole burden here.
"""

import pytest

from peritus.experts.avatar import (
    AVATAR_STYLES,
    SEED_MAX_CHARS,
    InvalidAvatar,
    normalise,
)
from peritus.experts.domain import Expert, ExpertStatus


def _expert(**kw) -> Expert:
    return Expert(
        id=1,
        name=kw.pop("name", "stoic-philosophy"),
        topic=kw.pop("topic", "Stoic philosophy"),
        status=ExpertStatus.READY,
        **kw,
    )


class TestNormalise:
    def test_none_and_empty_mean_derive(self):
        assert normalise(None) is None
        assert normalise({}) is None

    def test_full_recipe_survives(self):
        assert normalise({"style": "shapes", "seed": "Dr. Elena Vasquez"}) == {
            "style": "shapes",
            "seed": "Dr. Elena Vasquez",
            "hue": None,
        }

    def test_seed_is_optional(self):
        assert normalise({"style": "rings"}) == {"style": "rings", "seed": None, "hue": None}

    @pytest.mark.parametrize("hue", [262, 421, -1, 262.7, True, "violet"])
    def test_a_hue_is_discarded_there_are_no_per_expert_colours(self, hue):
        # Dropped rather than refused, so an older client that still sends one
        # saves its style instead of getting a 400.
        assert normalise({"style": "sigil", "hue": hue})["hue"] is None

    def test_unknown_keys_are_dropped_not_rejected(self):
        # An older server must not 400 on a field a newer client sends, but it
        # must not persist a field it cannot validate either.
        assert normalise({"style": "glass", "background": "#fff"}) == {
            "style": "glass",
            "seed": None,
            "hue": None,
        }

    @pytest.mark.parametrize("style", sorted(AVATAR_STYLES))
    def test_every_advertised_style_is_accepted(self, style):
        assert normalise({"style": style})["style"] == style

    @pytest.mark.parametrize(
        "style", ["avataaars", "lorelei", "personas", "micah", "openPeeps", "thumbs"]
    )
    def test_face_styles_are_refused(self, style):
        # The product reason, not a typo guard: a generated human face next to an
        # invented name reads as a claim that a real person wrote this.
        with pytest.raises(InvalidAvatar):
            normalise({"style": style})

    def test_missing_or_non_string_style_is_refused(self):
        with pytest.raises(InvalidAvatar):
            normalise({"seed": "x"})
        with pytest.raises(InvalidAvatar):
            normalise({"style": 7})

    def test_seed_is_trimmed_and_bounded(self):
        assert normalise({"style": "sigil", "seed": "  padded  "})["seed"] == "padded"
        long = normalise({"style": "sigil", "seed": "x" * (SEED_MAX_CHARS + 50)})
        assert len(long["seed"]) == SEED_MAX_CHARS

    def test_blank_seed_becomes_none(self):
        # "" would seed every generator identically; None means "derive it".
        assert normalise({"style": "sigil", "seed": "   "})["seed"] is None

    def test_non_string_seed_is_refused(self):
        with pytest.raises(InvalidAvatar):
            normalise({"style": "sigil", "seed": 42})

    def test_a_non_dict_is_refused(self):
        with pytest.raises(InvalidAvatar):
            normalise(["shapes"])  # type: ignore[arg-type]
