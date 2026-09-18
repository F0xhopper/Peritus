import { describe, expect, it } from 'vitest'

import { mayReadWhole } from '@/lib/source-kind'

/**
 * Whether the reader *offers* the whole of a source.
 *
 * The API decides what it will actually serve (`_whole_text_allowed` in
 * `routes/sources.py`); this is the display gate, and the point of testing it
 * separately is that the two must not drift — an action offered on a source the
 * API will not reproduce sends a reader to a page that explains it cannot show
 * them what they clicked for.
 */
describe('offering the whole of a source', () => {
  it('offers the kinds whose text is free to reproduce', () => {
    for (const source_type of ['gutenberg', 'wikipedia', 'arxiv']) {
      expect(mayReadWhole({ source_type }, false)).toBe(true)
    }
  })

  it('does not offer anything else, however it was read', () => {
    for (const source_type of ['exa', 'web', 'thought_leader', 'reddit', 'youtube', 'pdf']) {
      expect(mayReadWhole({ source_type, full_text_method: 'html' }, true)).toBe(false)
    }
  })

  it('offers a paper read through a resolved open-access copy', () => {
    // `oa_…` is the one licence fact the pipeline records.
    expect(mayReadWhole({ source_type: 'openalex', full_text_method: 'oa_pdf_url' }, false)).toBe(
      true
    )
    expect(
      mayReadWhole({ source_type: 'openalex', full_text_method: 'landing_page_url' }, false)
    ).toBe(false)
  })

  it('offers an upload to its owner only', () => {
    expect(mayReadWhole({ source_type: 'upload' }, true)).toBe(true)
    expect(mayReadWhole({ source_type: 'upload' }, false)).toBe(false)
  })

  it('never offers an abstract, which has nothing more to read', () => {
    expect(mayReadWhole({ source_type: 'arxiv', full_text_method: 'abstract' }, true)).toBe(false)
  })
})
