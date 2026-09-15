-- Migration 026: a picture avatar per expert that its owner can change.
--
-- Until now an expert's identity was derived on the client from its persona
-- name: same name, same colour, same monogram, everywhere. That is a good
-- default and it stays the default — but it is not choosable, and it moves. A
-- rebuild writes a new persona name, the hash changes, and an expert the user
-- had learned to recognise in the rail silently becomes a different colour.
--
-- This column is the override. NULL means "derive from the persona name",
-- exactly as before, so every existing expert keeps the identity it has and
-- nothing is backfilled. A non-null value is a choice the owner made and is
-- authoritative from then on.
--
-- Stored as JSONB rather than three columns because the payload is a rendering
-- recipe, not data anything queries: no index wants it, no report groups by it,
-- and a future style with an extra parameter should not need a migration.
--
--   {"style": "shapes", "seed": "Dr. Elena Vasquez", "hue": 262}
--
--   style  which generator draws it: one of the abstract DiceBear collections
--          the web client ships, or "sigil" for the built-in monogram. Never a
--          face style — a generated face beside an invented name reads as a
--          claim that a real person exists.
--   seed   what the generator is seeded with. Defaults to the persona name,
--          but is stored separately so re-rolling the picture does not require
--          renaming the expert.
--   hue    0–359, the accent that tints the expert's pages. NULL inside the
--          object means "derive the hue too", which is what a user gets when
--          they change only the picture.
--
-- The CHECK is deliberately shallow: it guarantees an object (so the client can
-- read `avatar.style` without a type test) and bounds the hue, and leaves the
-- style vocabulary to the API layer, which is where a new style is added.

ALTER TABLE experts
    ADD COLUMN IF NOT EXISTS avatar JSONB;

DO $$
BEGIN
    ALTER TABLE experts
        ADD CONSTRAINT experts_avatar_shape_check
        CHECK (
            avatar IS NULL
            OR (
                jsonb_typeof(avatar) = 'object'
                AND jsonb_typeof(avatar -> 'style') = 'string'
                AND (
                    avatar -> 'hue' IS NULL
                    OR jsonb_typeof(avatar -> 'hue') = 'null'
                    OR (
                        jsonb_typeof(avatar -> 'hue') = 'number'
                        AND (avatar ->> 'hue')::numeric >= 0
                        AND (avatar ->> 'hue')::numeric < 360
                    )
                )
            )
        );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
