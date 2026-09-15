/**
 * Rendering an expert's avatar.
 *
 * **Three levels of precedence, and the order is the whole design:**
 *
 *     avatar (the owner's recipe)  →  picture (found)  →  sigil (derived)
 *
 * The *recipe* (`{style, seed}`) is a choice someone made, so it wins over
 * everything. Below it sits the **found picture**: a real, licensed image of the
 * expert's subject — the bust that heads the Wikipedia article, not a headshot
 * of the persona — which the build finds and stores. Below that is the derived
 * monogram, which is what an expert with neither looks like.
 *
 * Nothing is uploaded at any level. The recipe is drawn from a pure function,
 * and the picture is fetched, licence-checked and stored server-side, then
 * served same-origin from our own API — so there is still no user-supplied
 * image and no third-party origin in the browser.
 *
 * DiceBear's generators are pure functions producing an SVG string, so this
 * runs in a Server Component as happily as in the browser and the first paint
 * already has the picture in it. Only abstract collections are wired up: a
 * generated human face beside an invented name would read as a claim that a
 * real person wrote the answers. (`thumbs` is excluded for that reason too —
 * it looks abstract at thumbnail size but is a face generator.)
 *
 * The allowlist here mirrors `api/src/peritus/experts/avatar.py`, which is the
 * authority; an unknown style from a newer server degrades to the monogram.
 */

import { createAvatar } from '@dicebear/core'
import { glass, icons, identicon, rings, shapes } from '@dicebear/collection'

export type AvatarStyle =
  | 'sigil'
  | 'shapes'
  | 'glass'
  | 'rings'
  | 'identicon'
  | 'icons'
  /** The found picture. Not in `AVATAR_STYLES` — see below. */
  | 'picture'

export interface AvatarRecipe {
  style: AvatarStyle
  seed: string | null
}

/**
 * The *generated* styles the picker's grid offers, in order.
 *
 * `picture` is deliberately absent: it is not a drawing anyone can pick from a
 * grid, it exists only when this expert actually has a found picture, and the
 * picker surfaces it as its own option above the grid. Including it here would
 * offer every expert a style most of them cannot render.
 */
export const AVATAR_STYLES: { style: AvatarStyle; label: string; hint: string }[] = [
  { style: 'sigil', label: 'Monogram', hint: 'Initials on a tinted tile' },
  { style: 'shapes', label: 'Shapes', hint: 'Overlapping geometry' },
  { style: 'glass', label: 'Glass', hint: 'Soft translucent blobs' },
  { style: 'rings', label: 'Rings', hint: 'Concentric arcs' },
  { style: 'identicon', label: 'Identicon', hint: 'Symmetric tile grid' },
  { style: 'icons', label: 'Icon', hint: 'A single line mark' },
]

const STYLE_SET = new Set<string>([...AVATAR_STYLES.map((s) => s.style), 'picture'])

export function isAvatarStyle(value: unknown): value is AvatarStyle {
  return typeof value === 'string' && STYLE_SET.has(value)
}

export interface AvatarSubject {
  persona_name?: string | null
  name?: string
  topic?: string
  /** The API still carries a `hue` on older rows; it is ignored. */
  avatar?: { style?: string; seed?: string | null } | null
  /** Only `version` is needed to draw it — the rest of the provenance is for
   *  the credit line, which the tile itself never renders. */
  picture?: { version: string } | null
}

/**
 * The recipe actually used to draw this expert: the stored one where it exists,
 * the derived one where it does not, and the derived halves filled in where the
 * owner pinned only a style.
 */
export function resolveRecipe(subject: AvatarSubject): AvatarRecipe {
  const persona = subject.persona_name?.trim()
  const derivedSeed = persona || subject.name || subject.topic || 'expert'
  const stored = subject.avatar
  const hasPicture = Boolean(subject.picture?.version)

  // No recipe: the found picture if there is one, else the monogram. This is
  // what makes `{avatar: null}` — the picker's Reset — mean "back to the
  // picture" rather than "back to two letters".
  if (!stored) {
    return { style: hasPicture ? 'picture' : 'sigil', seed: derivedSeed }
  }

  // A stored `picture` style on an expert whose picture has since been removed
  // degrades to the monogram, which is the same fallback an unknown style gets.
  const style = isAvatarStyle(stored.style) ? stored.style : 'sigil'
  return {
    style: style === 'picture' && !hasPicture ? 'sigil' : style,
    seed: stored.seed?.trim() || derivedSeed,
  }
}

/**
 * True when nothing about this avatar was chosen by its owner.
 *
 * Unchanged by the picture: a found picture is still a default the expert
 * arrived with, not a decision, and a rebuild that renames the expert would
 * still change the monogram underneath it. What it gates is the picker's
 * Reset button and the "this is derived" hint.
 */
export function isDerived(subject: AvatarSubject): boolean {
  return !subject.avatar
}

export interface AvatarPalette {
  strong: string
  mid: string
  soft: string
}

/**
 * The one palette every generated drawing uses: the design's own grey ramp,
 * very slightly cool (`--fg-3` is #6b6b73) so an avatar matches the neutral
 * text beside it. There are no per-expert colours.
 */
export const AVATAR_PALETTE: AvatarPalette = { strong: '6b6b73', mid: '9a9aa2', soft: 'dedee3' }

/** Where the found picture's bytes live, same-origin and cache-busted. */
export function pictureUrl(expertSlug: string, version: string): string {
  // The `?v=` is the image's content hash. The bytes are served with
  // `immutable` and a year's max-age, which is only safe because a different
  // picture is a different URL — so this must always carry the version.
  return `/api/experts/${encodeURIComponent(expertSlug)}/picture?v=${encodeURIComponent(version)}`
}

/**
 * The SVG for a generated style, as a string. `sigil` returns null — the
 * monogram is a React component, because it needs the initials rule and the
 * theme's live `--expert` variable rather than a baked hex.
 *
 * `rings` and `identicon` draw on transparency; the component puts them on the
 * soft tile, so they are not handed a background here.
 */
export function renderAvatarSvg(recipe: AvatarRecipe, size: number): string | null {
  // Neither of these is a generated drawing: `sigil` is a React component (it
  // needs the initials rule and the live `--expert` variable), and `picture` is
  // an `<img>` the component renders itself.
  if (recipe.style === 'sigil' || recipe.style === 'picture') return null
  const seed = recipe.seed || 'expert'
  const { strong, mid, soft } = AVATAR_PALETTE
  const common = { seed, size }

  switch (recipe.style) {
    case 'shapes':
      return createAvatar(shapes, {
        ...common,
        backgroundColor: [soft],
        shape1Color: [strong],
        shape2Color: [mid],
        shape3Color: [strong],
      }).toString()

    case 'glass':
      return createAvatar(glass, { ...common, backgroundColor: [mid, strong] }).toString()

    case 'rings':
      return createAvatar(rings, { ...common, ringColor: [strong, mid] }).toString()

    case 'identicon':
      return createAvatar(identicon, { ...common, rowColor: [strong] }).toString()

    case 'icons':
      // The collection hardcodes the mark as `fill="#fff"`, which is invisible
      // on the soft tile. Recolouring the emitted fill is the only way to get
      // it into the palette — the style exposes no colour option.
      return createAvatar(icons, { ...common, backgroundColor: [soft] })
        .toString()
        .replace(/fill="#fff"/g, `fill="#${strong}"`)

    default:
      return null
  }
}

/** A fresh random seed, for the picker's shuffle control. */
export function randomSeed(): string {
  return Math.random().toString(36).slice(2, 12)
}
