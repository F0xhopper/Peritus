/**
 * Per-expert visual identity, *derived* from the persona name.
 *
 * This is the default half of the identity. The owner can override it — see
 * `lib/avatar.ts` and `experts.avatar` — but until they do, every expert's
 * monogram is computed here and must be deterministic: the same
 * expert has to look the same on every page, in every session, and in the TUI.
 * The hash is the same `h*31 + codepoint` the Rust client uses
 * (`cli/src/tui/widgets/avatar.rs`), and `personaInitials` is a direct port of
 * its `initials()` — including the honorific rule, because every persona is a
 * "Dr." and a wall of DR badges identifies nobody.
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

/** The persona name if there is one, else the topic, else the slug. */
export function displayName(expert: {
  persona_name?: string | null
  topic?: string
  name?: string
}): string {
  return expert.persona_name || expert.topic || expert.name || 'Expert'
}

/**
 * The line under a name: the topic, or null when the name already *is* the
 * topic. An expert with no persona is titled by its topic, and printing it
 * again underneath read "Thomism / Thomism" on every card, tooltip and header.
 */
export function subtitle(expert: {
  persona_name?: string | null
  topic?: string
  name?: string
}): string | null {
  const topic = expert.topic?.trim()
  return topic && topic !== displayName(expert) ? topic : null
}

export interface ExpertIdentity {
  initials: string
  /** A stable 0–5 seed for the sigil's background marks. */
  seed: number
}

export function expertIdentity(expert: {
  persona_name?: string | null
  name?: string
  topic?: string
}): ExpertIdentity {
  const label = expert.persona_name?.trim() || expert.name || expert.topic || 'expert'
  return {
    initials: personaInitials(label),
    seed: nameHash(label) % 6,
  }
}
