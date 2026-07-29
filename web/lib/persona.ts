// An expert is somebody you consult, not a row in a table — so it is named and
// titled everywhere it appears. The persona generator is instructed to hand
// back a doctored name ("Dr. Elena Vasquez"), but experts built before that
// instruction landed came back bare, so the title is also applied at render
// time. That keeps one rule in one place instead of a `Dr. ${...}` template
// scattered across every surface that prints a persona.

/** Names that already carry an honorific keep the one they have — promoting a
 * Professor or a Sir to a Dr. is a demotion they did not ask for. Matched on a
 * word boundary so a persona actually called "Drummond" is not read as "Dr". */
const HONORIFIC =
  /^(dr|prof|professor|sir|dame|rev|fr|st|mx|mr|mrs|ms|lord|lady|capt|captain|maj|major|col|colonel|gen|general)\b\.?\s/i;

/**
 * The name to print for an expert's persona, titled.
 *
 * Returns null when there is no persona yet — a queued or failed expert has
 * never reached the persona stage, and inventing a doctor for it would claim
 * an authority the build never produced. Callers fall back to the topic.
 */
export function personaLabel(name: string | null | undefined): string | null {
  const trimmed = name?.trim();
  if (!trimmed) return null;
  return HONORIFIC.test(trimmed) ? trimmed : `Dr. ${trimmed}`;
}

/**
 * Up to two letters for an avatar.
 *
 * The honorific is stripped first: every expert is a Dr., so a grid of "DR"
 * monograms would identify nobody. Falls back to the first letter of whatever
 * it was given (a topic, for personaless experts).
 */
export function personaInitials(label: string): string {
  const words = label
    .replace(HONORIFIC, "")
    .split(/\s+/)
    .filter((word) => /\p{L}|\p{N}/u.test(word));

  if (words.length === 0) return "?";

  const letters = words
    .slice(0, 2)
    .map((word) => Array.from(word)[0])
    .join("");
  return letters.toUpperCase();
}
