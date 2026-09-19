/**
 * Per-expert naming and visual identity.
 *
 * **An expert is named by its subject.** The build still writes a persona — a
 * name like "Dr. Marta Belen" and an About line — and the persona still sets
 * how answers are written, but it is not shown as who the expert is. An invented
 * doctor with an invented career sat badly beside a product whose one promise
 * is that nothing it says is made up, borrowed an authority no one holds, and
 * said nothing about the subject: every card needed the topic underneath to be
 * readable. The subject is what people remember an expert by, and unlike the
 * persona it survives a rebuild.
 *
 * This is the default half of the identity. The owner can override it — see
 * `lib/avatar.ts` and `experts.avatar` — but until they do, every expert's
 * monogram is computed here and must be deterministic: the same
 * expert has to look the same on every page, in every session, and in the TUI.
 * The hash is the same `h*31 + codepoint` the Rust client uses
 * (`cli/src/tui/widgets/avatar.rs`), and `personaInitials` is a direct port of
 * its `initials()`, honorific rule included (harmless on a subject, and the TUI
 * still labels an expert by its persona).
 *
 * **There are no per-expert colours.** Every expert is monochrome; what tells
 * experts apart is the avatar — the found picture, a generated drawing, or the
 * monogram. Colour in the product means status and nothing else.
 */

const HONORIFICS = new Set([
  'dr',
  'prof',
  'professor',
  'sir',
  'dame',
  'rev',
  'fr',
  'st',
  'mx',
  'mr',
  'mrs',
  'ms',
  'lord',
  'lady',
  'capt',
  'captain',
  'maj',
  'major',
  'col',
  'colonel',
  'gen',
  'general',
])

/**
 * `h * 31 + codepoint`, wrapping at 32 bits. Identical to the Rust client's, so
 * an expert's identity is stable across both front ends.
 */
export function nameHash(label: string): number {
  let hash = 0
  for (const ch of label) {
    hash = (Math.imul(hash, 31) + (ch.codePointAt(0) ?? 0)) | 0
  }
  return Math.abs(hash)
}

/**
 * Up to two letters for the monogram. The honorific is stripped when something
 * follows it; a bare "Dr" is still a name. Splits on hyphens and underscores so
 * a persona-less expert falls back cleanly from its slug ("stoic-philosophy" →
 * "SP").
 */
export function personaInitials(label: string | null | undefined): string {
  if (!label) return '?'
  const words = label.split(/[\s\-_]+/).filter((w) => /[\p{L}\p{N}]/u.test(w))

  if (words.length > 1) {
    const bare = words[0].replace(/\.+$/, '').toLowerCase()
    if (HONORIFICS.has(bare)) words.shift()
  }

  const letters = words
    .slice(0, 2)
    .map((w) => w.match(/[\p{L}\p{N}]/u)?.[0] ?? '')
    .join('')
    .toUpperCase()

  return letters || '?'
}

/**
 * The expert's name: its subject, as typed when it was built, with a capital
 * first letter ("thomism" → "Thomism"). A row without a topic falls back to its
 * slug, spaced out.
 */
export function displayName(expert: { topic?: string; name?: string }): string {
  const label = expert.topic?.trim() || expert.name?.replace(/[-_]+/g, ' ').trim()
  if (!label) return 'Expert'
  return label.charAt(0).toLocaleUpperCase('en') + label.slice(1)
}

export interface ExpertIdentity {
  initials: string
  /** A stable 0–5 seed for the sigil's background marks. */
  seed: number
}

/**
 * The monogram's letters come from the name people see — the subject — and its
 * background marks from the slug, which never changes, so a rebuild leaves the
 * tile exactly as it was.
 */
export function expertIdentity(expert: { name?: string; topic?: string }): ExpertIdentity {
  const slug = expert.name || expert.topic || 'expert'
  return {
    initials: personaInitials(expert.topic?.trim() || slug),
    seed: nameHash(slug) % 6,
  }
}
