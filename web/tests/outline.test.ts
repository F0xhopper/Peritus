import { describe, expect, it } from 'vitest'

import {
  closeShare,
  isUnstructured,
  locusRange,
  narrowOutline,
  partName,
  readingInWords,
} from '@/lib/brain/outline'
import type { OutlinePart, OutlineResponse, OutlineWork } from '@/lib/api/types'

function part(overrides: Partial<OutlinePart> = {}): OutlinePart {
  return {
    label: null,
    held: false,
    seq_start: 0,
    seq_end: 9,
    passages: 10,
    passage_id: 1,
    locus_first: null,
    locus_last: null,
    key_concepts: [],
    section_count: 0,
    sections: null,
    ...overrides,
  }
}

function work(overrides: Partial<OutlineWork> = {}): OutlineWork {
  return {
    source_id: 1,
    title: 'Summa Theologica, Part I',
    author: 'Thomas Aquinas',
    kind: 'gutenberg',
    tier: 'primary',
    passages: 10,
    close: 10,
    held: 0,
    locus_first: null,
    locus_last: null,
    parts: [part()],
    ...overrides,
  }
}

function outline(works: OutlineWork[]): OutlineResponse {
  return {
    expert: { slug: 'thomism', topic: 'Thomism' },
    computed: true,
    key_concepts: [],
    totals: { works: works.length, passages: 0, close: 0, held: 0, parts: 0, sections: 0 },
    works,
  }
}

describe('locusRange', () => {
  it('collapses two loci in the same place to a range of their last number', () => {
    expect(locusRange('I, q. 2, a. 1', 'I, q. 2, a. 3')).toBe('I, q. 2, a. 1–3')
    expect(locusRange('Book II, Chapter 1', 'Book II, Chapter 9')).toBe('Book II, Chapter 1–9')
  })

  it('writes both ends out when they are different places', () => {
    expect(locusRange('I, q. 35, a. 2', 'I, q. 66, a. 4')).toBe('I, q. 35, a. 2 – I, q. 66, a. 4')
    expect(locusRange('A.D. 16', 'A.D. 942')).toBe('A.D. 16 – A.D. 942')
    expect(locusRange('Question 2', 'I, q. 2, a. 3')).toBe('Question 2 – I, q. 2, a. 3')
  })

  it('never abbreviates a last component that is not a number', () => {
    expect(locusRange('Part I, Preface', 'Part I, Chapter 37')).toBe('Part I, Preface – Chapter 37')
  })

  it('is one locus when there is one, and nothing when there is none', () => {
    expect(locusRange('I, q. 9, a. 1', 'I, q. 9, a. 1')).toBe('I, q. 9, a. 1')
    expect(locusRange('Book I', null)).toBe('Book I')
    expect(locusRange(null, 'Book I')).toBe('Book I')
    expect(locusRange(null, null)).toBeNull()
  })
})

describe('partName', () => {
  it('is the heading, with the place beside it', () => {
    expect(
      partName(
        part({
          label: 'The Existence of God',
          locus_first: 'I, q. 2, a. 1',
          locus_last: 'I, q. 2, a. 3',
        })
      )
    ).toEqual({ title: 'The Existence of God', place: 'I, q. 2, a. 1–3' })
  })

  it('is the place when the text has no heading, and says it once', () => {
    expect(partName(part({ locus_first: 'I, q. 36, a. 1', locus_last: 'I, q. 36, a. 4' }))).toEqual(
      { title: 'I, q. 36, a. 1–4', place: null }
    )
  })

  it('has no name when there is neither — a source with no structure', () => {
    expect(partName(part())).toEqual({ title: null, place: null })
    expect(isUnstructured(work())).toBe(true)
    expect(isUnstructured(work({ parts: [part({ label: 'Introduction' })] }))).toBe(false)
    expect(isUnstructured(work({ parts: [part(), part()] }))).toBe(false)
  })
})

describe('narrowOutline', () => {
  const summa = work({
    parts: [
      part({ label: 'The Existence of God' }),
      part({ label: 'Of the Simplicity of God', locus_first: 'I, q. 3, a. 1' }),
    ],
  })
  const ethics = work({
    source_id: 2,
    title: 'The Nicomachean Ethics',
    author: 'Aristotle',
    parts: [part({ label: 'Book I' })],
  })

  it('leaves everything standing with nothing typed', () => {
    const rows = narrowOutline(outline([summa, ethics]), '  ')
    expect(rows.map((row) => [row.work.source_id, row.parts.length, row.byPart])).toEqual([
      [1, 2, false],
      [2, 1, false],
    ])
  })

  it('keeps every part of a work that matched by title or author', () => {
    const rows = narrowOutline(outline([summa, ethics]), 'aristotle')
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ byPart: false, parts: ethics.parts })
  })

  it('keeps only the matching parts otherwise, by heading or by place, and says so', () => {
    const byHeading = narrowOutline(outline([summa, ethics]), 'simplicity')
    expect(byHeading).toHaveLength(1)
    expect(byHeading[0].byPart).toBe(true)
    expect(byHeading[0].parts.map((p) => p.label)).toEqual(['Of the Simplicity of God'])
    expect(narrowOutline(outline([summa, ethics]), 'q. 3')[0].parts).toHaveLength(1)
    expect(narrowOutline(outline([summa, ethics]), 'kant')).toEqual([])
  })
})

describe('reading', () => {
  it('is the share read closely', () => {
    expect(closeShare({ close: 218, passages: 614 })).toBeCloseTo(0.355, 3)
    expect(closeShare({ close: 0, passages: 0 })).toBe(0)
  })

  it('is said in words, and never says "0 held"', () => {
    expect(readingInWords({ passages: 2433, close: 1620, held: 813 })).toBe(
      '1620 of 2433 passages read closely, 813 held'
    )
    expect(readingInWords({ passages: 525, close: 525, held: 0 })).toBe(
      '525 passages, all read closely'
    )
    expect(readingInWords({ passages: 1, close: 1, held: 0 })).toBe('1 passage, all read closely')
  })
})
