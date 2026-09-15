import { describe, expect, it } from 'vitest'

import { closeOpenMarkdown, splitBlocks } from '@/components/chat/markdown'

/**
 * How an answer is cut into memoised Markdown blocks, and how a half-streamed
 * block is made renderable.
 *
 * The split exists for streaming performance, and every case below is a way it
 * used to break the Markdown it was splitting.
 */

describe('splitBlocks', () => {
  it('splits paragraphs and headings at blank lines', () => {
    expect(splitBlocks('One.\n\n## Two\n\nThree.')).toEqual(['One.', '## Two', 'Three.'])
  })

  it('never splits inside a fenced code block', () => {
    const fence = '```\nline one\n\nline two\n```'
    expect(splitBlocks(`Before.\n\n${fence}\n\nAfter.`)).toEqual(['Before.', fence, 'After.'])
  })

  it('keeps a loose ordered list in one block, so numbering does not restart', () => {
    const list = '1. First\n\n2. Second\n\n3. Third'
    expect(splitBlocks(list)).toEqual([list])
  })

  it('keeps an indented continuation paragraph inside its list item', () => {
    const list = '1. First\n2. Second\n\n   More about the second.\n\n3. Third'
    expect(splitBlocks(list)).toEqual([list])
  })

  it('still ends a list at a following paragraph', () => {
    expect(splitBlocks('- a\n- b\n\nAfterwards.')).toEqual(['- a\n- b', 'Afterwards.'])
  })

  it('ignores trailing blank lines rather than emitting an empty block', () => {
    expect(splitBlocks('Para.\n\n')).toEqual(['Para.'])
    expect(splitBlocks('')).toEqual([''])
  })
})

describe('closeOpenMarkdown', () => {
  it('closes an unterminated strong span', () => {
    expect(closeOpenMarkdown('roughly **double e')).toBe('roughly **double e**')
  })

  it('closes an unterminated emphasis span, but not a list bullet', () => {
    expect(closeOpenMarkdown('- *Deformed win')).toBe('- *Deformed win*')
    expect(closeOpenMarkdown('* a bullet')).toBe('* a bullet')
  })

  it('closes an open code fence', () => {
    expect(closeOpenMarkdown('```\ngrams = 35')).toBe('```\ngrams = 35\n```')
  })

  it('closes inline code', () => {
    expect(closeOpenMarkdown('written as `3.5% w')).toBe('written as `3.5% w`')
  })

  it('drops a citation marker cut off mid-number', () => {
    expect(closeOpenMarkdown('a clean-up [1')).toBe('a clean-up ')
  })

  it('holds back a list marker or heading hash with nothing after it yet', () => {
    expect(closeOpenMarkdown('1. First\n2. ')).toBe('1. First\n')
    expect(closeOpenMarkdown('Intro.\n## ')).toBe('Intro.\n')
  })

  it('leaves balanced text alone', () => {
    const text = 'A **bold** and *italic* and `code` sentence [2].'
    expect(closeOpenMarkdown(text)).toBe(text)
  })
})
