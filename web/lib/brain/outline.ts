import type { OutlinePart, OutlineResponse, OutlineWork } from '@/lib/api/types'

/**
 * The Outline view's arithmetic: how a range of loci is written, what a part is
 * called, and which works and parts a search leaves standing. Pure, like the
 * map's layout and the Flow's, so the rules are asserted and not eyeballed
 * (`tests/outline.test.ts`).
 */

/** "I, q. 2, a. 3" → ["I, q. 2", "a. 3"]; "A.D. 878" → [null, "A.D. 878"]. */
function splitLocus(locus: string): [string | null, string] {
  const at = locus.lastIndexOf(',')
  if (at < 0) return [null, locus]
  return [locus.slice(0, at).trim(), locus.slice(at + 1).trim()]
}

/**
 * A part's place in its work, as one phrase.
 *
 * Two loci in the same place collapse to a range of their last component —
 * "I, q. 2, a. 1–3", not the locus twice — because a column of forty repeated
 * prefixes is what made the first render unreadable. Anything else is written
 * out in full with a spaced dash: the two ends are then different places, and
 * abbreviating one of them would be a guess.
 */
export function locusRange(first: string | null, last: string | null): string | null {
  const from = first ?? last
  const to = last ?? first
  if (!from || !to) return null
  if (from === to) return from

  const [fromGroup, fromLeaf] = splitLocus(from)
  const [toGroup, toLeaf] = splitLocus(to)
  if (fromGroup !== null && fromGroup === toGroup) {
    const a = /^(\D*)(\d+)$/.exec(fromLeaf)
    const b = /^(\D*)(\d+)$/.exec(toLeaf)
    if (a && b && a[1] === b[1]) return `${fromGroup}, ${a[1]}${a[2]}–${b[2]}`
    return `${fromGroup}, ${fromLeaf} – ${toLeaf}`
  }
  return `${from} – ${to}`
}

/**
 * What a part is called, and what is said beside it.
 *
 * A heading where the text has one; its place where it does not — a held
 * stretch of the Summa with no headings is still "I, q. 36, a. 1–4", which is
 * what a reader of the Summa would call it anyway. A part with neither is a
 * source with no structure at all, and the view does not list it as a row.
 */
export function partName(part: OutlinePart): { title: string | null; place: string | null } {
  const place = locusRange(part.locus_first, part.locus_last)
  if (part.label) return { title: part.label, place }
  return { title: place, place: null }
}

/** A work whose only part has no name: nothing to list under it but its sections. */
export function isUnstructured(work: OutlineWork): boolean {
  return work.parts.length === 1 && partName(work.parts[0]).title === null
}

/** The share of a work's passages that were read closely, 0–1. */
export function closeShare(work: Pick<OutlineWork, 'close' | 'passages'>): number {
  return work.passages > 0 ? work.close / work.passages : 0
}

export interface NarrowedWork {
  work: OutlineWork
  /** The parts left standing; all of them when the work itself matched. */
  parts: OutlinePart[]
  /** True when the text matched a part and not the work — so it opens. */
  byPart: boolean
}

/**
 * The works a search leaves, and within each the parts.
 *
 * A work matches on its title or author and then keeps every part; otherwise it
 * stays only for the parts whose heading or place matches, and says so, so the
 * view can open it — a match the reader has to go looking for is not a match.
 */
export function narrowOutline(outline: OutlineResponse, text: string): NarrowedWork[] {
  const needle = text.trim().toLowerCase()
  if (!needle) return outline.works.map((work) => ({ work, parts: work.parts, byPart: false }))
  const out: NarrowedWork[] = []
  for (const work of outline.works) {
    if (`${work.title} ${work.author ?? ''}`.toLowerCase().includes(needle)) {
      out.push({ work, parts: work.parts, byPart: false })
      continue
    }
    const parts = work.parts.filter((part) => {
      const { title, place } = partName(part)
      return `${title ?? ''} ${place ?? ''}`.toLowerCase().includes(needle)
    })
    if (parts.length) out.push({ work, parts, byPart: true })
  }
  return out
}

/** "1,620 of 2,433 passages read closely; 813 held", for the header and a screen reader. */
export function readingInWords(
  totals: Pick<OutlineResponse['totals'], 'passages' | 'close' | 'held'>,
  format: (n: number) => string = String
): string {
  const noun = totals.passages === 1 ? 'passage' : 'passages'
  if (totals.held === 0) return `${format(totals.passages)} ${noun}, all read closely`
  return `${format(totals.close)} of ${format(totals.passages)} ${noun} read closely, ${format(totals.held)} held`
}
