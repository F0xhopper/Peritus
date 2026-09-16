import { describe, expect, it } from 'vitest'

import {
  AVATAR_STYLES,
  isAvatarStyle,
  isDerived,
  AVATAR_PALETTE,
  pictureUrl,
  randomSeed,
  renderAvatarSvg,
  resolveRecipe,
} from '@/lib/avatar'
import { nameHash, personaInitials } from '@/lib/persona'

/**
 * Avatar identity.
 *
 * The properties that matter are determinism and stability: the same expert has
 * to look identical on every page, in every session, and — for the hash and the
 * initials — in the Rust TUI, which computes them the same way.
 */

const derived = {
  name: 'varroa-mite-control',
  persona_name: 'Dr. Marta Belen',
  topic: 'Varroa mite control',
  avatar: null,
}

describe('nameHash', () => {
  it('matches the Rust client’s h*31 + codepoint', () => {
    // "EV" → the same value the TUI computes, which is what keeps one expert's
    // identity consistent across both front ends.
    expect(nameHash('')).toBe(0)
    expect(nameHash('a')).toBe(97)
    expect(nameHash('ab')).toBe(97 * 31 + 98)
  })

  it('is deterministic and non-negative', () => {
    for (const label of ['Dr. Elena Vasquez', 'stoic-philosophy', '', '🐝 bees']) {
      expect(nameHash(label)).toBe(nameHash(label))
      expect(nameHash(label)).toBeGreaterThanOrEqual(0)
    }
  })

  it('wraps at 32 bits without overflowing to Infinity', () => {
    const long = 'x'.repeat(500)
    expect(Number.isFinite(nameHash(long))).toBe(true)
  })
})

describe('personaInitials', () => {
  it('strips the honorific, because every persona is a Dr.', () => {
    expect(personaInitials('Dr. Elena Vasquez')).toBe('EV')
    expect(personaInitials('Professor Ada Lovelace')).toBe('AL')
    expect(personaInitials('Prof Ada Lovelace')).toBe('AL')
  })

  it('keeps a name that merely starts like an honorific', () => {
    expect(personaInitials('Drummond Field')).toBe('DF')
  })

  it('keeps a bare honorific, which is still the only name there is', () => {
    expect(personaInitials('Dr')).toBe('D')
    expect(personaInitials('Dr.')).toBe('D')
  })

  it('splits a slug on hyphens and underscores', () => {
    expect(personaInitials('stoic-philosophy')).toBe('SP')
    expect(personaInitials('varroa_mite_control')).toBe('VM')
  })

  it('falls back to a question mark rather than rendering nothing', () => {
    expect(personaInitials('')).toBe('?')
    expect(personaInitials(null)).toBe('?')
    expect(personaInitials(undefined)).toBe('?')
    expect(personaInitials('...')).toBe('?')
  })

  it('handles non-Latin scripts', () => {
    expect(personaInitials('Ελένη Βασκέζ')).toBe('ΕΒ')
  })
})

describe('resolveRecipe', () => {
  it('derives the monogram from the persona name when nothing is stored', () => {
    expect(resolveRecipe(derived)).toEqual({ style: 'sigil', seed: 'Dr. Marta Belen' })
  })

  it('seeds a persona-less expert from its slug', () => {
    const building = { name: 'queued-topic', persona_name: null, avatar: null }
    expect(resolveRecipe(building)).toEqual({ style: 'sigil', seed: 'queued-topic' })
  })

  it('seeds from the slug, not the topic, so two experts on one topic differ', () => {
    const a = resolveRecipe({ name: 'beekeeping', topic: 'Beekeeping', persona_name: null })
    const b = resolveRecipe({ name: 'beekeeping-2', topic: 'Beekeeping', persona_name: null })
    expect(a.seed).not.toBe(b.seed)
  })

  it('honours a stored recipe outright', () => {
    const recipe = resolveRecipe({ ...derived, avatar: { style: 'shapes', seed: 'pinned' } })
    expect(recipe).toEqual({ style: 'shapes', seed: 'pinned' })
  })

  it('ignores a hue an older row still carries — there are no per-expert colours', () => {
    const stored = { style: 'shapes', seed: 'pinned', hue: 145 } as { style: string; seed: string }
    expect(resolveRecipe({ ...derived, avatar: stored })).toEqual({
      style: 'shapes',
      seed: 'pinned',
    })
  })

  it('fills in the derived seed when only a style is pinned', () => {
    const recipe = resolveRecipe({ ...derived, avatar: { style: 'rings', seed: null } })
    expect(recipe).toEqual({ style: 'rings', seed: 'Dr. Marta Belen' })
  })

  it('degrades an unknown style to the monogram rather than rendering nothing', () => {
    // A newer server offering a style this build cannot draw.
    const recipe = resolveRecipe({
      ...derived,
      avatar: { style: 'some-future-generator', seed: 'x' },
    })
    expect(recipe.style).toBe('sigil')
  })
})

describe('resolveRecipe with a found picture', () => {
  /**
   * The three levels of precedence — recipe, picture, monogram — are the whole
   * design, and the middle one is new. What these pin is that the build's find
   * never overrides a person's choice, and that Reset lands on the picture
   * rather than skipping past it to two letters.
   */
  const withPicture = { ...derived, picture: { version: '9f3a1c2b7d4e' } }

  it('shows the picture when the owner has chosen nothing', () => {
    expect(resolveRecipe(withPicture)).toEqual({ style: 'picture', seed: 'Dr. Marta Belen' })
  })

  it('never overrides a recipe the owner pinned', () => {
    const recipe = resolveRecipe({
      ...withPicture,
      avatar: { style: 'shapes', seed: 'pinned' },
    })
    expect(recipe.style).toBe('shapes')
  })

  it('degrades a pinned picture style to the monogram once the picture is gone', () => {
    // Remove deletes the row; the recipe pointing at it is now a dangling
    // reference, and must fall back exactly as an unknown style does.
    const recipe = resolveRecipe({
      ...derived,
      avatar: { style: 'picture', seed: null },
    })
    expect(recipe.style).toBe('sigil')
  })

  it('falls to the monogram when there is no picture and no recipe', () => {
    expect(resolveRecipe({ ...derived, picture: null }).style).toBe('sigil')
  })
})

describe('pictureUrl', () => {
  it('always carries the version, because the cache is immutable', () => {
    expect(pictureUrl('varroa-mite-control', '9f3a1c2b7d4e')).toBe(
      '/api/experts/varroa-mite-control/picture?v=9f3a1c2b7d4e'
    )
  })

  it('escapes a slug so it cannot alter the path', () => {
    expect(pictureUrl('a/b', 'v1')).toBe('/api/experts/a%2Fb/picture?v=v1')
  })
})

describe('isDerived', () => {
  it('is true only when nothing is stored', () => {
    expect(isDerived(derived)).toBe(true)
    expect(isDerived({ ...derived, avatar: { style: 'sigil' } })).toBe(false)
  })

  it('is still true for an expert showing its found picture', () => {
    // A found picture is a default the expert arrived with, not a decision —
    // so Reset stays disabled and the "this is derived" hint still applies.
    expect(isDerived({ ...derived, picture: { version: 'abc123abc123' } })).toBe(true)
  })
})

describe('isAvatarStyle', () => {
  it('accepts every style the picker offers', () => {
    for (const option of AVATAR_STYLES) expect(isAvatarStyle(option.style)).toBe(true)
  })

  it('accepts the picture style, which the grid deliberately does not offer', () => {
    // It is not a drawing anyone picks from a grid — it exists only where the
    // expert actually has a found picture — but it is a real stored style and
    // must round-trip rather than degrading to the monogram.
    expect(isAvatarStyle('picture')).toBe(true)
    expect(AVATAR_STYLES.some((o) => o.style === 'picture')).toBe(false)
  })

  it('rejects the face generators the server also refuses', () => {
    for (const style of ['avataaars', 'lorelei', 'personas', 'thumbs', 'bottts']) {
      expect(isAvatarStyle(style)).toBe(false)
    }
  })

  it('rejects non-strings', () => {
    expect(isAvatarStyle(null)).toBe(false)
    expect(isAvatarStyle(7)).toBe(false)
  })
})

describe('AVATAR_PALETTE', () => {
  it('is the near-grey ramp, dark to light', () => {
    // Very slightly cool, like `--fg-3` (#6b6b73): red and green equal, blue a
    // shade higher, so an avatar matches the neutral text beside it.
    const { strong, mid, soft } = AVATAR_PALETTE
    const channels = (hex: string) =>
      [0, 2, 4].map((at) => Number.parseInt(hex.slice(at, at + 2), 16))
    for (const value of [strong, mid, soft]) {
      expect(value).toMatch(/^[0-9a-f]{6}$/)
      const [r, g, b] = channels(value)
      expect(r).toBe(g)
      expect(b - r).toBeGreaterThanOrEqual(0)
      expect(b - r).toBeLessThan(16)
    }
    const sum = (hex: string) => channels(hex).reduce((x, y) => x + y, 0)
    expect(sum(strong)).toBeLessThan(sum(mid))
    expect(sum(mid)).toBeLessThan(sum(soft))
  })
})

describe('renderAvatarSvg', () => {
  it('returns null for the monogram, which is a React component', () => {
    expect(renderAvatarSvg({ style: 'sigil', seed: 'x' }, 32)).toBeNull()
  })

  it('renders every generated style as an SVG at the requested size', () => {
    for (const option of AVATAR_STYLES) {
      if (option.style === 'sigil') continue
      const svg = renderAvatarSvg({ style: option.style, seed: 'Dr. Marta Belen' }, 48)
      expect(svg, option.style).toContain('<svg')
      expect(svg, option.style).toContain('width="48"')
    }
  })

  it('is byte-identical for the same recipe', () => {
    const recipe = { style: 'shapes' as const, seed: 'Dr. Marta Belen' }
    expect(renderAvatarSvg(recipe, 40)).toBe(renderAvatarSvg(recipe, 40))
  })

  it('changes with the seed', () => {
    const base = { style: 'shapes' as const, seed: 'a' }
    expect(renderAvatarSvg(base, 40)).not.toBe(renderAvatarSvg({ ...base, seed: 'b' }, 40))
  })

  it('paints the icon style in the palette rather than leaving it white', () => {
    // The collection hardcodes `fill="#fff"`, which is invisible on the tile.
    const svg = renderAvatarSvg({ style: 'icons', seed: 'bee' }, 48)!
    expect(svg).not.toContain('fill="#fff"')
    expect(svg).toContain(`fill="#${AVATAR_PALETTE.strong}"`)
  })
})

describe('randomSeed', () => {
  it('is a short URL-safe string, and different each time', () => {
    const seeds = Array.from({ length: 50 }, () => randomSeed())
    for (const seed of seeds) expect(seed).toMatch(/^[a-z0-9]{1,10}$/)
    expect(new Set(seeds).size).toBeGreaterThan(45)
  })
})
